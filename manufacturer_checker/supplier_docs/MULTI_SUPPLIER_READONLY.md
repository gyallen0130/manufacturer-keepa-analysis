# 卸問屋横断の共通正規化・照会MVP（2026-11-08／開発用）

## 目的

今後の最優先方針は、**特定1社の見積価格を繰り返し調べることではなく、3〜5社の異なる資料から共通項目を抽出し、候補商品と原本へ戻れること**。開発コード[ `multi_source_readonly.py` ](multi_source_readonly.py)で既存の`parser.parse_rows`を一度に最大5資料へ適用し、結果を非公開の明細と公開安全な件数へ分離する。

**これは既存Google Drive/SheetsのAPIを直接呼ぶプログラムではない。** ChatGPTや許可されたプライベート実行環境が、既に読み取った**1～5個の限定行範囲**を渡したときだけ解析する。Driveを勝手に全巡回せず、GCP/GitHub Actions等の追加課金や認証変更は不要。

## 2026-11-08に実際の見出しを確認した4社

原本の必要な先頭部分だけを接続済みGoogle Driveで閲覧。以下は **列見出しに関する実測**であって、このPythonの実資料実行結果ではない。商品行・JAN/ASIN・価格は本ドキュメントに記録しない。

| 取引先と検査タブ | 先頭20行内の主な列見出し | 共通項目上の注意 |
| --- | --- | --- |
| [株式会社井上／「見積もり」](https://docs.google.com/spreadsheets/d/1qakllf_kkwnpzrOIIRs-oqLiffINjVUa4fIRT0gnl5U/edit) | 1行目：メーカー／商品名／商品名（Amazon）／JAN／品番／上代(税抜）／発注単位／下代(税抜） | `品番`を`model_number`、下代税抜を`cost_tax_mode='excluded'`へ。上代（希望小売価格相当）を仕入コストとして扱わない |
| [ワコーフーズ／「新田ゼラチン」](https://docs.google.com/spreadsheets/d/1MxnvUDWz7JWj5_dKtxN9iYiOOZUcTfhd7G4H_yRmke8/edit) | 1行目：商品名／商品名（Amazon）／ASIN／JAN／発注単位／卸値（税込） | `卸値（税込）`は税込のコスト列。ただしメーカー名のタブは**原本の行のメーカー名を証明しない**。タブ名だけで`manufacturer_name_raw`を埋めない |
| [ヨシダ／「GEX」](https://docs.google.com/spreadsheets/d/1i1VZUViLNK9WCUOwH3g7rbubfPGr0GfC6M8eleLh0RM/edit) | 1行目：メーカー／商品名／商品名（Amazon）／ASIN／JAN／発注単位（ケース/カートン）／BOX入り数×ケース内ボックス数／卸価格／税込仕入れ値 | 価格列が複数で**内容や単位が異なる**。今の安全な共通パーサーでは両者の価格を単純に1つの`cost_amount`へ選ばず、要確認とする |
| [株式会社イトウ／「シート1」](https://docs.google.com/spreadsheets/d/1kLd8GVwYp0rzwKRM_8t9rp5RRGyCJuHqxifxb1D8naQ/edit) | 3行目：商品名／JAN／ASIN | 見出し行が3行目のため1行目を固定ヘッダーとしない。見積依頼側のSheetsと返信Excelは別の原本であり、無条件に同じ価格表としてマージしない |

## 共通正規化処理

```python
from supplier_docs.multi_source_readonly import (
    normalize_selected_sources, search_selected_sources,
)

# 以下はダミーID・架空JAN/商品である。
samples = [
    {
        'source_file_id': 'DEMO_SOURCE_001',
        'source_sheet': 'シート1',
        'source_url': 'https://example.invalid/sheet',
        'document_type': 'quote_request',
        'rows': [
            ['商品名', 'JAN', 'ASIN'],
            ['架空マスク', '0000000000017', 'B0TEST0001'],
        ],
    },
]
result = normalize_selected_sources(samples)
# 出してよいのは件数等の集計だけ。
print(result['public_summary'])
# JANは完全一致、商品名は正規化した部分一致。
hits = search_selected_sources(
    result, field='jan', query='0000000000017')
print(hits['public_summary'])

# 次は元Driveと照合する必要のあるPRIVATE参照。公開しない。
private_docs = result['private_normalized_docs']
private_hits = hits['private_hits']
```

- 受入形式：`document_type`を明示した1～5資料。資料ごと1～200物理行、1行40列以内。商品候補が記録にない場合は未照合範囲を別途記載する。
- **`public_summary`に実JAN、ASIN、商品名、原本ID、実原価は含めない**。行数・抽出件数・既知フィールドの被覆率・警告件数だけ。
- `private_normalized_docs`には各資料の`source_url / source_sheet / source_row / mapped_columns`と商品別JAN/ASIN等が含まれる。**許可された非公開の一時処理だけ**で使用し、Private GitHub索引にも詳細行を複写しない。
- `search_selected_sources`は**あらかじめ読み込んだ1～5資料のローカル検索のみ**。JANとASINは厳格な完全一致。商品名・メーカー名・型番は正規化した部分一致。検索ヒットは原本の行番号まで戻せるが、同一SKU、仕入可、現在の販売単位、見積有効性は確定しない。
- `mapped_source_counts`は、何社でその列見出しが共通項目に写像されたかの件数。**該当値が完全で正しいという意味ではない**。税区分が不明・価格列が曖昧なら安全側で未確定にする。
- **画像PDFはまだ処理対象外**。Excelは原本を別途適切に読み取って2次元行配列として渡せるが、このモジュールそのものはExcel/Google SheetsのファイルI/Oをしない。

## CIと実運用の線引き

2026-11-08に調べた4社の**列見出し構造を模した架空の商品データ**を[15件のテスト](../tests/test_supplier_multi_source_readonly.py)で正規化・照会する。実JAN/価格・取引先の個別商品をCIへ渡さない。結果は正規化できる形のソフトウェア上の実証であり、**実際の4社の全商品行をプログラムに投入する一連の実運用試験ではない**。

次の工程で、権限のある私的実行環境から**1～5社の少量の実原本行をこの処理へ渡す**接続を安全に設計する。照合件数と問題点だけを公開安全な進捗へ記録し、秘匿原価や本番認証は扱わない。

方針：[Private共通知識の複数卸優先ルール](https://github.com/gyallen0130/amazon-business-knowledge/blob/main/suppliers/cross-supplier-development-priority.md)。Draft PR #1の範囲内・未マージ、本番WIF/Keepa/SP-APIへの変更なし。
