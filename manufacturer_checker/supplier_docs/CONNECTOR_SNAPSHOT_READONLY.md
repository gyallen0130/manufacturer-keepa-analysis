# Google Drive接続済みの実SheetsをPythonへ渡す手動・非公開スナップショット入口

2026-11-08追加。**Google Sheets v4の新しいOAuth/サービスアカウント資格情報をPythonへ渡さず**、既存の認証済みGoogle Driveコネクタで取得した**事前選択1～5シートの行列**を一時的なPrivate Python処理へ渡す。[connector_sheet_snapshot.py](connector_sheet_snapshot.py)が、Excelと同じ共通正規化・検索へ渡す。

## 2つの入力経路と違い

| 入力方式 | 値の由来 | 注意点 |
| --- | --- | --- |
| `connector_formula_values` | 接続済みDriveの指定シート`get_spreadsheet_range`等で、**A1:O40・FORMULA**として取得済みの値 | Google APIの読取と可視性確認は**呼出元が実施**。Python関数自身の`api_calls`は0であり、Google認証の成功を保証しない |
| `native_export_xlsx` | 接続済みDriveから**ネイティブGoogle Sheets全体をXLSXへ一時書き出し**、Private実行環境で指定タブの`A1:O40`だけを行列化 | **変換経路でセル型・数式の再現が異なる可能性**。全ブックのコピーをPrivateに置くので、対象外タブも含み得る。原本は書込禁止、GitHubへファイルを絶対にアップロードしない |

**前提**：資料の閲覧権限、対象ファイル・指定タブ・`FORMULA`読取を、認証済みの接続元が実行・確認していること。新モジュールには資格情報取得、Google API、Driveフォルダ自動列挙、ネットワークI/O、永続データ保存がない。**利用者による文字列の`snapshot_method`指定だけで本人の権限を検証できるわけではない**。

## 架空の使用例

```python
from supplier_docs.connector_sheet_snapshot import (
    SCHEMA_VERSION, MODE, normalize_selected_connector_snapshots,
)
from supplier_docs.mixed_source_readonly import combine_selected_source_results

# Private実行環境のメモリ内。以下は架空の行とIDのみ。
approved_rows = [
    ['商品名', 'JAN', 'ASIN'],
    ['架空商品', '0000000000017', 'B0TEST0001'],
]
manifest = {
    'schema_version': SCHEMA_VERSION,
    'mode': MODE,
    'sources': [{
        'spreadsheet_id': 'FAKE_GOOGLE_SHEET_001',
        'sheet_name': '架空シート',
        'document_type': 'quote_request',
        'snapshot_method': 'connector_formula_values',
        'rows': approved_rows,
    }],
}
sheets_private = normalize_selected_connector_snapshots(manifest=manifest)
# Excel側は別途、許可済みのprivate Excelを
# local_excel_bridge.inspect_selected_local_excel()で読む。
# combined = combine_selected_source_results([excel_private, sheets_private],
#                     search={'field':'jan','query':private_requested_jan})
print(sheets_private['public_summary'])  # 集計件数のみ
# PRIVATE rowsや個別のJAN・ASIN、原本URLは印字・保存しない。
```

## 範囲・安全基準

- 対象は**明示済み1～5シート、各最大40行×15列**。型はJSON相当の文字列・整数・実数・真偽・nullのみ。過剰入力、複合セル、不明な拡張キー、重複ID/タブ、不正な資料種別や検索語を拒否する。
- マッピングは従来の`header_row`、`tiered_mapping`、`row_labeled_mapping`のうち**いずれか1つ**。JAN/ASINとPOS/ITF、費用の税区分などは従来の安全判定を維持し、候補検索は仕入・SKU確定を意味しない。
- `native_export_xlsx`の場合は**たとえ元の解析で仕入価格・発注単位らしい列があっても、各商品の`cost_present=False`、`cost_tax_mode='unknown'`、`order_multiple=''`へ保留**する。プログラムが見積原価を信頼して利益を計算してはならない。
- 両方式とも`profit_calculation_allowed=False`、`purchase_allowed=False`、`source_writes=0`。`public_summary`には匿名件数・方法・警告だけ。生データは`private_normalized_docs`／`private_hits`。
- `connector_auth_verified_by_this_function=False`、`connector_reads_performed_by_this_function=0`。ここで`api_calls=0`と記録しているのは**外部接続の呼出しが0だったという意味ではない**。認証済みコネクタによる事前読取は別の監査ログに残る。
- PythonからGoogle Sheets APIへ**直接ログインする方式ではない**。時間指定実行、全112社巡回、WIF/サービスアカウントの権限変更、永続データ同期は未実装。

## 実資料検証（値を公開しない）

2026-11-08、認証済みGoogle Drive接続から取得した**ワコーフーズ実Google SheetsのXLSX書出し**を、Privateで`artifact_tool`を使い指定タブの**A1:O40**だけ行列化し、イトウの**実Excelの1タブ**とともに、開発ブランチの`connector_sheet_snapshot.py`→`mixed_source_readonly.py`へ入力した。

- **2社・2シートを解析**、商品候補**12行**、JAN欄候補**6行**、ASIN欄候補**9行**。両社からPrivateでASINを1件ずつ選び、**それぞれ限定検索で1ヒット、元の物理行を保持**。商品の同一性は**未確定**。
- 検証前後の両方の実Excelバイト列ハッシュは一致し、原本を書き換えていない。GitHub Actionsへ実商品行を送っていない。
- **同じ認証済みDriveコネクタによる`FORMULA`指定のレンジ読取とは区別**する。井上の実シートA1:O40で、接続の`FORMULA`取得では**数式セル28個**を確認した一方、同じシートのXLSX書出しを今回の`artifact_tool`解析経路で取り出した`formulas`には**1個**しか現れなかった。**これは書出し・読込のどの段階に差が生じたか未特定**。出所不一致の可能性があるため、XLSX書出しから見積単価・税区分・発注単位を確定しない。価格が必要な場合は原本の直接`FORMULA`取得を優先する。
- **実接続を使った手動の混在検索は検証済み**だが、PythonがGoogle Sheets APIへ新規に直接認証したわけではない。ChatGPT/Claudeへいつでも無人照会できる本番経路ではない。

[架空のコネクタスナップショットを使う13件のテスト](../tests/test_supplier_connector_sheet_snapshot.py)で入力上限・価格保留・秘密非出力・Excelとの混在検索を検証。

