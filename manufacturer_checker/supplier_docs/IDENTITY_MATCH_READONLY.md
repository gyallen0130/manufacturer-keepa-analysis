# 複数の取引先資料をまたぐ商品候補照合（開発用・実運用未接続）

## 何を実装したか

`identity_matcher.py` は、同じ取引先または別の取引先から取得した**二つの解析済みレコード列**をオフラインで比較する小さな部品です。`supplier_docs.parser.parse_rows` が返すレコード、または同じキーを持つ許可済みの私的レコードを入力します。

- **一切のAPI呼出し、ファイル/DB書込、数式計算、マクロ実行、Amazon販売・発注判断を行わない**。
- 入力は両側最大200レコード。件数オーバー、不適切な配列、ASINリスト形式の破損は停止する。
- 比較するキー：JAN/GTIN（先頭0を維持しチェックデジット検証）、ASIN候補（B0以外も10文字なら扱う）、商品名、任意の型番、`pack_quantity`、`capacity` / `size`。
- `order_multiple` は**卸の発注ロット**であり、消費者向けの1パック入数と同一扱いしない。
- 識別子が一種類だけ一致しても**有力確定商品にはしない**。商品名不一致・JAN/ASIN不一致・容量/入数不一致があれば `conflict`。複数候補行が同じレコードに結び付くときは自動で弱い判定へ下げる。
- **結果が `strong_candidate` でも「販売可能な確定SKU」ではない**。外部のメーカー仕様、Amazon販売単位、見積時点、取引条件、出品許可は別途確認する。
- **2026-11-08 実原本で見つかった落とし穴**：同じExcelに「JAN」見出しが2列あり、6商品行のうち3行で両列の値が異なる例を確認。**1列だけを選んでJAN/ASIN/商品名が一致しても、そのまま強い一致と判定しない**。`mark_duplicate_jan_headers(records, header_row)`で元の見出しを検査し、`jan_source_ambiguous`フラグを新しいレコードのコピーへ伝える。列の業務上の意味が確認されるまで、強い一致は`id_candidate`へ降格し`jan_columns_require_review`を付ける。元の値や原本を変更しない。
- **JANがExcelの数値型の場合**：`_gtin`は安全のため、数値型をJANとして受け入れない。13桁に見えても先頭0や元の表示形式の問題を確認する。形式・チェックデジットを検査した一時的な文字列化は照合の**条件付き比較**にとどめ、確定商品としては扱わない。
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

## 2つの「JAN」列と見積回答の記録（2026-11-08追加）

同じExcelに`JAN`見出しが複数あっても、**どちらかを「正しいJAN」と機械的に選ばない**ために、[quote_jan_audit.py](quote_jan_audit.py)を新設した。

`inspect_explicit_jan_columns(rows, header_row_index=2, request_jan_column=1, reply_jan_column=3, reply_note_columns=(3,4,5))`に、呼び出し側が**原本の列位置を明示**して渡す。引数名の「request」「reply」は暫定的な位置の役割名であり、契約上どちらが見積依頼か／正式回答かを認定するものではない。

- **same_as_displayed**：2つのJAN欄の表示上の番号が一致。数値型のセルの場合は先頭0・表示形式が保証されないので商品確定ではない。
- **different_as_displayed**：2列の表示番号が違う。**代替JANの提案／誤記／違う商品の可能性**を勝手に決めず確認対象にする。
- **historical_unavailable_note**：「廃番」「取扱終了」などの語が指定した回答側の欄にある。**原本当時の記載**であり、現在の商品状態・在庫状態を保証しない。
- **missing_or_unreadable**：必要な番号がない、形式不明など、同一商品確認ができない。

集計の`public_summary`には件数と状態名だけを記録し、`private_row_evidence`には原本の1始まりの行番号と理由コードだけを持たせる。JAN・ASIN・原価・商品名をGitHubに保存しない。新しい結果から`attach_jan_audit_to_records(records, physical_row_numbers=[...], audit=...)`で**行番号を明示的に対応付けたコピー**へ`jan_source_ambiguous=True`を付ける。行が欠けた／順番不一致／重複した場合は拒否する。これにより既存の`identity_matcher`は曖昧な行を`strong_candidate`に上げない。

この検証の根拠は[イトウの実原本比較（Private知識リポジトリ）](https://github.com/gyallen0130/amazon-business-knowledge/blob/main/suppliers/pilots/itou-jan-column-roles-2026-11-08.md)。**実原本で観察した構造をもとに設計し、プログラムの回帰テストは架空データのみで行った**。この新モジュールを実取引先のファイルへ本番自動適用したという意味ではない。GitHubのDraft PRのまま。

## JAN列の見出し事前判定（複数取引先の誤検出を防止）

2026-11-08に、**井上・ワコーフーズの実Google Sheets見積タブの限定範囲ではJAN見出しがそれぞれ1列**であることを確認。対照的にイトウの見積返信Excelでは2列だった。

`quote_jan_audit.summarize_jan_header_structure(header_row)` は**見出しだけ**を受け取り、`single`／`duplicate_needs_review`／`missing` のいずれかと件数だけを返す。値・価格・原本JANを公開ログに出さず、`single` なら**2列照合はそもそも実施しない**。`duplicate_needs_review` でも原本の依頼／回答メールを確認してから2列を明示的に指定し、推測で正本を決めない。`missing` の資料を「JANなし商品」とも断定しない。

- 依頼JANと返信JANが異なる2商品について、2026-11-08に**メーカー公式ページの該当製品に返信側コードが掲載されている**ことを外部照合した。ただし依頼時のコードとのメーカー公式な新旧対応は未確認で、**strong_candidateへの格上げはしない**。
- 公開メーカー資料の検証概要は[共通知識側の匿名記録](https://github.com/gyallen0130/amazon-business-knowledge/blob/main/suppliers/pilots/itou-official-jan-crosscheck-2026-11-08.md)。JAN／ASIN／個別見積金額は本リポジトリには保存しない。
- 新関数のテストは架空の見出しだけで実行する。Google Drive原本に対してこのPython関数を実際に一括起動するものではない。

## Amazon販売単位とメーカー個装の違い（2026-11-08追加）

[offer_pack_guard.py](offer_pack_guard.py)で、**メーカー個装50枚**と**Amazonの「1ASINが何箱か」**、**見積単価の購入単位（1箱・複数箱）**、卸の**ケース入数**を混同しないチェックを追加した。Amazonの商品詳細を自動取得する機能ではない。

2026-11-08に外部のAmazon情報転載サイトを調べると、対象のマスク候補で`50枚×4箱`／`50枚×2箱`という掲載があった。一方メーカー公式の個装は各`50枚`。**Amazon本体の現在の販売単位は直接検証できなかった**ので、転載を`amazon_direct_verified`として扱わず、`secondary_listing`とする。メーカーの旧新JANの正式対応や商品同一性も未確認で、確定SKUや仕入利益を推定しない。

次の例は**架空の商品**であり、価格・実ASIN・実JANや原本のSKU行を公開しない：

```python
from supplier_docs.offer_pack_guard import (
    evaluate_offer_pack_guard, mark_records_from_pack_guard,
)

# ケース入数は物流単位。見積の「1単価が何箱分か」は未確認。
quote = {'items_per_inner_box': 50, 'case_pack': 50}
listing = {'items_per_inner_box': 50, 'inner_boxes_per_offer': 4,
           'source': 'secondary_listing'}
guard = evaluate_offer_pack_guard(quote, listing)
assert guard['public_summary']['status'] == 'needs_quoted_purchase_unit'
assert guard['public_summary']['profit_calculation_allowed'] is False

# privateな許可済み行にフラグだけを付けて、既存の比較器に渡せる。
private_rows = [{'asin_candidate': 'B0TEST0001',
                 'product_name_raw': '架空マスク'}]
guarded_rows = mark_records_from_pack_guard(private_rows, guard)
assert guarded_rows[0]['offer_pack_review_required'] is True
```

`mark_records_from_pack_guard`で販売単位が未検証のレコードへ`offer_pack_review_required=True`を付けると、[identity_matcher.py](identity_matcher.py)でJAN・ASIN・商品名が一致しても`strong_candidate`とせず、`id_candidate`（`offer_pack_unit_requires_review`）に抑える。原本レコードは改変しない。

**重要な制約**：`case_pack`を`inner_boxes_per_quoted_unit`に流用してはいけない。原本の購入単位が明示・検証されていなければ判定を保留する。`source='amazon_direct_verified'`を渡すのは、使用者側が実際にAmazonの該当ASIN・選択バリエーション・箱数を直接確認した場合に限る。どんな入力でも、この独立ガードは利益計算・発注を許可しない。

[17件の架空データテスト](../tests/test_supplier_offer_pack_guard.py)で2箱・4箱・単位不明・外部転載・単位一致・型異常・既存商品照合器への確認フラグ伝播を検証。原本取引データやAmazon認証はテストに不要。実調査の出典・保留事項は[共通知識側の記録](https://github.com/gyallen0130/amazon-business-knowledge/blob/main/suppliers/pilots/itou-amazon-packaging-risk-2026-11-08.md)に保管する。**現時点ではDraft PR内の開発部品で、本番ワークフローへは接続しない。**

## 別日の販促メールの「ケース入数」と「単価」は見積の価格単位の証明ではない

2026-11-08に業務用メールを読取検証した。対象のメーカー50枚入りマスクの別日付の案内で、`ケース入数50箱`と`単価`が記載されていたが、**2025年8月に依頼した別の見積の単価が「小箱1箱分」とは明記されていない**。

`offer_pack_guard.quote_unit_from_document_evidence(evidence)`は、使用者が原本の来歴を確認した上で、**対象見積そのもの**の単価対象箱数が明確なときだけ`quote_unit_verified=True`の情報を渡す。それ以外は保留する。価格・JAN/ASIN・メールIDなどは返さない。

```python
from supplier_docs.offer_pack_guard import (
    quote_unit_from_document_evidence, evaluate_offer_pack_guard,
)

# 別日の架空販促メールでは、その見積の単価が何箱分か分からない。
provenance = quote_unit_from_document_evidence({
    'scope': 'other_promotion',
    'kind': 'case_pack_and_price_only',
    'case_pack': 50,       # 倉庫・配送用のケース入数にすぎない
})
assert provenance['public_summary']['quote_unit_verified'] is False
unknown_quote = {
    'items_per_inner_box': 50,
    **provenance['private_guard_quote'],
}
secondary_listing = {
    'items_per_inner_box': 50,
    'inner_boxes_per_offer': 4,
    'source': 'secondary_listing',
}
risk = evaluate_offer_pack_guard(unknown_quote, secondary_listing)
assert risk['public_summary']['status'] == 'needs_quoted_purchase_unit'
assert risk['public_summary']['profit_calculation_allowed'] is False
```

`scope='target_quote', kind='explicit_per_retail_box'`を指定できるのは**その見積の単価対象箱数を実際に確認した場合のみ**である。過去の販促メール・ケース入数・Amazon情報の二次転載を単価1箱あたりの根拠へ昇格させてはならない。この関数は入力した情報が本物かをオンラインで照合せず、認証・メール取得・本番利益計算を行わない。

[業務側の出所を区別した確認記録](https://github.com/gyallen0130/amazon-business-knowledge/blob/main/suppliers/pilots/itou-quote-unit-evidence-2026-11-08.md)。テストは架空情報だけ、実メール・仕入価格はPublic GitHubに保存しない。

## 未実装・未確認

- この関数は、既存 `on_demand_reader.inspect_manual_approved_sheets(...)` の戻り値に含まれる **`private_inspections[i]['tabs'][j]['records']`** を、許可済みの非公開処理から明示的に選んで呼べる。ただし自動選択・常時監視・商品同一性の最終確定は行わない。
- **このモジュールを既存の本番Google Sheets/Excel/PDF収集処理、Keepa利益計算、Amazon発注、Private Actions WIFへは接続していない**。GitHubのDraft PR #1内のレビュー用コードである。
- メーカーの実JAN・数値型で先頭0を失ったもの、外部Excel数式の値、画像PDFの読み取った値、Amazonの商品画像と販売単位は、各原本の追加確認が必要。
- Claudeを今すぐ導入する必要はない。純粋なPython処理とMarkdown文書なのでAIサービスの切替・併用は可能。

共通知識での対応：[業務側の横断照合方針](https://github.com/gyallen0130/amazon-business-knowledge/blob/main/suppliers/product-identity-cross-source-guide.md)。GitHubの索引には実原価、商品別JAN/ASIN行や詳細判定結果を保存しない。
