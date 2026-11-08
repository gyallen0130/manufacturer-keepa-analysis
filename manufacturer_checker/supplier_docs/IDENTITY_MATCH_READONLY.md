# 複数の取引先資料をまたぐ商品候補照合（開発用・実運用未接続）

## 何を実装したか

`identity_matcher.py` は、同じ取引先または別の取引先から取得した**二つの解析済みレコード列**をオフラインで比較する小さな部品です。`supplier_docs.parser.parse_rows` が返すレコード、または同じキーを持つ許可済みの私的レコードを入力します。

- **一切のAPI呼出し、ファイル/DB書込、数式計算、マクロ実行、Amazon販売・発注判断を行わない**。
- 入力は両側最大200レコード。件数オーバー、不適切な配列、ASINリスト形式の破損は停止する。
- 比較するキー：JAN/GTIN（先頭0を維持しチェックデジット検証）、ASIN候補（B0以外も10文字なら扱う）、商品名、任意の型番、`pack_quantity`、`capacity` / `size`。
- `order_multiple` は**卸の発注ロット**であり、消費者向けの1パック入数と同一扱いしない。
- 識別子が一種類だけ一致しても**有力確定商品にはしない**。商品名不一致・JAN/ASIN不一致・容量/入数不一致があれば `conflict`。複数候補行が同じレコードに結び付くときは自動で弱い判定へ下げる。
- **結果が `strong_candidate` でも「販売可能な確定SKU」ではない**。外部のメーカー仕様、Amazon販売単位、見積時点、取引条件、出品許可は別途確認する。
- 実原価、商品名、JAN、ASIN、資料IDはコードやCI/公開ログに保存しない。

## 最も簡単な使い方（すべて架空データ）

```python
from supplier_docs.parser import parse_rows
from supplier_docs.identity_matcher import compare_supplier_rows

# 実際に使うときは、権限を確認したGoogle Drive原本やExcelの
# *必要な範囲だけ*を既存readerで読み、外部へコピーしない。
a = parse_rows(
    [['メーカー', '商品名', 'ASIN'],
     ['架空メーカー', '架空商品A', 'B0TEST0001']],
    document_type='quote_request')
b = parse_rows(
    [['メーカー', '商品名', 'ASIN'],
     ['架空メーカー', '架空商品A', 'B0TEST0001']],
    document_type='quote_request')

result = compare_supplier_rows(a['records'], b['records'])

# 通常ログや一般的な進捗表示に使えるのは集計だけ。
print(result['public_summary'])
# private_pairs には行番号に相当するindexと判定コードが入る。
# 実原本と突き合わせる場合は、閲覧許可された非公開の処理内で
# a['records'][index] / b['records'][index] を参照すること。
# これらの明細は公開CIログやGitHubのMarkdownへ複写しない。
```

## 戻り値

`public_summary` は行数・候補組数・ステータス別件数のみ。例えば `confirmed_saleable_skus: 0`、`decision: human_review_required` が常に含まれる。

`private_pairs` は両側の **0始まりindex・status・evidence_codes** だけ。実のJAN/ASIN/商品名は戻り値に含まれないが、indexは元の機密行との関連を示すため**必要なときだけ非公開で使用**する。

判定ステータス：
- `strong_candidate`：JAN・ASIN・名称が一致し、既知の矛盾やASIN複数候補・多対多がない。ただしSKU確定ではない。
- `id_candidate`：JANまたはASINだけの一致、またはASIN複数候補等による保守的な降格。
- `name_only`：正規化した商品名だけ一致する。JAN・ASIN・セット仕様は未確認。
- `conflict`：いずれかが一致して候補となったが、ほかの既知の識別子や型番／容量／セット数量が矛盾。
- `insufficient`：現時点の結果では候補にできない。このモジュールでは「未一致行」をsummaryの `unmatched_a_rows` / `unmatched_b_rows` に含め、個別の `insufficient` ペアを無理に生成しない。

## 再現用テスト

```bash
cd manufacturer_checker
python -m unittest -v tests.test_supplier_identity_matcher tests.test_supplier_identity_integration
```

このテストは**架空のJAN/ASIN/原価・商品名**のみを使う。Google Drive/Keepa/SP-APIや秘密鍵は使わない。元の機密業務データをGitHub Actionsのログへ流す手順ではない。

## 未実装・未確認

- この関数は、既存 `on_demand_reader.inspect_manual_approved_sheets(...)` の戻り値に含まれる **`private_inspections[i]['tabs'][j]['records']`** を、許可済みの非公開処理から明示的に選んで呼べる。ただし自動選択・常時監視・商品同一性の最終確定は行わない。
- **このモジュールを既存の本番Google Sheets/Excel/PDF収集処理、Keepa利益計算、Amazon発注、Private Actions WIFへは接続していない**。GitHubのDraft PR #1内のレビュー用コードである。
- メーカーの実JAN・数値型で先頭0を失ったもの、外部Excel数式の値、画像PDFの読み取った値、Amazonの商品画像と販売単位は、各原本の追加確認が必要。
- Claudeを今すぐ導入する必要はない。純粋なPython処理とMarkdown文書なのでAIサービスの切替・併用は可能。

共通知識での対応：[業務側の横断照合方針](https://github.com/gyallen0130/amazon-business-knowledge/blob/main/suppliers/product-identity-cross-source-guide.md)。GitHubの索引には実原価、商品別JAN/ASIN行や詳細判定結果を保存しない。
