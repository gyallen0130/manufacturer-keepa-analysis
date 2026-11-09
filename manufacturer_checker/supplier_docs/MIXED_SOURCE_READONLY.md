# Excel＋Google SheetsのPrivate検索結果を共通照合する試験版

2026-11-08追加。実原本をコピーしてGitHubに置く代わりに、**すでに読み取られた承認済みのPrivateな結果**を、同じ非公開実行環境のメモリ上だけで一緒に検索する。

## 役割分担

- `local_excel_bridge.inspect_selected_local_excel`：許可済みの私的ローカルExcel(.xlsx/.xlsm)の指定1～5タブ、各A1:O40。
- `sheets_multi_bridge.inspect_selected_google_sheets`：**別途認証済みの読取専用**Google Sheets v4クライアントと明示した指定タブ、各A1:O40。
- [`mixed_source_readonly.combine_selected_source_results`](mixed_source_readonly.py)：**Excel結果1つ＋Sheets結果1つを受け**、合計最大5タブに制限してプライベートな照合空間を作る。**この結合コード自体は通信しない**。
- [`multi_source_readonly.search_selected_sources`](multi_source_readonly.py)：JAN／ASIN／POS／ITF／型番等の**選択資料内限定**の検索。POS候補とJANを自動同一視しない。

### 架空の使用例

```python
from supplier_docs.local_excel_bridge import inspect_selected_local_excel
from supplier_docs.sheets_multi_bridge import inspect_selected_google_sheets
from supplier_docs.mixed_source_readonly import combine_selected_source_results

# 以下は実運用値ではなく、既存のPrivate manifestが手元にある前提の例。
# 認証済みのSheets v4読取専用clientも事前に別途用意する。
excel_private_result = inspect_selected_local_excel(
    root_dir='/private/excel',
    manifest=private_excel_manifest,
)
sheets_private_result = inspect_selected_google_sheets(
    sheets_service=authorized_readonly_client,
    manifest=private_sheets_manifest,
)
mixed = combine_selected_source_results(
    [excel_private_result, sheets_private_result],
    search={'field': 'jan', 'query': private_requested_jan},
)
print(mixed['public_summary'])        # 集計件数のみ、原本IDを含まない
print(mixed['public_search_summary']) # 集計件数のみ、検索語を含まない
# mixed['private_normalized_docs'] / ['private_hits']
# / ['private_source_kinds'] は機密情報を含むのでCIやGitHubに出さない。
```

## 実装されている安全側の動作

- **両形式の実接続結果を受けるだけ**。ChatGPTのGoogle Driveコネクタの認証をPythonへ自動移譲するものではない。自動巡回・継続同期・有料サービス導入・発注はしない。
- 対象は**合計5タブまで**。元のソースID＋シート名、元の`source_row`、`source_kind`をPrivateに保持。不正な行番号／ソース件数／書込可能のような結果／旧スキーマは拒否する。
- `parsed`／`mapped_review`／`labeled_review`／`needs_review`／`empty`を区別。未解析タブ・検索不能な項目の0件ヒットを**全卸で該当なしと誤認しない**。
- POSとITFは、**元の商品行に「POSコード」「ITFコード」の明示ラベルがあり、適切な形式・チェックデジットであることが確認された候補**。JANとして確定しない。
- `public_summary`に原本ファイル名、行内の商品名、JAN/ASIN/POS/ITF、価格、原本URL、検索語を出さない。商品明細とヒットの行番号はPrivate返値のみ。
- `confirmed_product_matches=0`、`profit_calculation_allowed=false`、`purchase_allowed=false`。Google/Amazonの商品や販売セット数の一致を証明したものではない。

## テストと残作業

[合成Excel(.xlsm)とGoogle Sheets v4模擬サービスを結合した11件のテスト](../tests/test_supplier_mixed_source_readonly.py)をGitHub Actionsで実行。JANを両形式で検索すると2件、POSだけだと1件のPrivateヒットを検出し、原本不変、公開集計の非漏洩、破損した結果の拒否を確認。

**実ExcelでのPOS/ITF抽出関数の直接E2Eは完了**：[Private知識Repoの匿名検証記録](https://github.com/gyallen0130/amazon-business-knowledge/blob/main/suppliers/pilots/row-labeled-pos-itf-real-e2e-and-mixed-search-2026-11-08.md)。ただし**実Google Sheetsと実Excelを同一Python環境でまとめて検索したE2Eは未完了**。次は既存の読取専用認証と明示した数タブだけで同時試験する。新規IAM/Secretsや本番WIF操作はしない。

