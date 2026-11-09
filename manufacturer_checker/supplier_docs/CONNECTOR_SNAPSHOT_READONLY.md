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



## 2026-11-09: 実Google認証をPythonに移さない「Excel＋Sheets一括検索」入口

新規の [connector_mixed_one_shot.py](connector_mixed_one_shot.py) は、認証済みのChatGPT/Google Driveコネクタから**必要なシート範囲だけを事前に取得**した場合に、それを同じ非公開プロセス内でExcelと横断検索できる、単純な開発用入口である。

- **GitHub Actions→WIFや専用Readerの実認証が未完成でも**、ChatGPTに接続済みのGoogle Driveを利用する手動の実務検証を進められる。
- Excelマニフェストは既存の`manual-local-excel-v1`。Sheetsスナップショットは`manual-connector-sheet-snapshot-v1`。**両方合わせて5タブ以内、各A1:O40**。ChatGPT/Driveが先に該当ファイルの権限・タブ名を確認する。
- **GoogleのOAuthトークンはPythonへ渡さない**。シートの元行列は許可されたprivateプロセスのメモリ中だけで扱い、関数が返すのは匿名`public_summary`と`public_search_summary`のみ。原本行・検索語・仕入原価・ファイルIDは戻り値に含まれない。
- `api_calls=0`は**このPython関数自身**のAPI呼び出し回数であり、事前にChatGPTのDriveコネクタがした読取件数ではない。外部認証検証も`False`のまま。
- **本番自動同期、実Google APIへのPython直接ログイン、利益判定・発注は依然未完成**。追加課金・IAM/WIF更新・Private RepoへのWorkflow追加を行わない。

プライベートなPythonプロセスで、認可済みの値を**変数として渡すだけ**の使用例：

```python
from supplier_docs.connector_mixed_one_shot import inspect_private_connector_mixed

# approved_excel_manifest はPrivate内の承認済みExcel設定。
# private_connector_manifest は、既存Google Driveコネクタが取得した
# 最大40行・15列のFORMULA行列を含むPrivateメモリ内の辞書。
result = inspect_private_connector_mixed(
    root_dir="/private/approved-excel",
    excel_manifest=approved_excel_manifest,
    connector_sheet_manifest=private_connector_manifest,
    search={"field": "asin", "query": private_requested_asin},
)
print(result["public_summary"])  # 匿名統計のみ
```

呼出元は、検索条件と取得した元セル値を**公開CI、開発リポジトリ、ログ、チャット内の引用に貼り付けない**。入力は事前に取得した実データでも、**今回追加したテスト自体は架空データ**。新規[9件の合成データ安全テスト](../tests/test_supplier_connector_mixed_one_shot.py)で検索・5タブ上限・出力抑止・非更新・失敗時の停止を検査する。

## 2026-11-09: 実原本のFORMULAセルを保持した2資料の直接混在解析E2E

ChatGPTの既存Google Drive接続が、認証済みの井上「見積もり」タブ **A1:O40** を`FORMULA`指定で読取。取得された**28件の数式を実行・評価せずリテラル文字列として保持**したまま、Private Python実行環境へ安全に受け渡し、沖縄県物産公社の実Excel **1タブ A1:O40** と`connector_mixed_one_shot.inspect_private_connector_mixed`で**実データE2E成功**。GoogleトークンはPythonへ提供していない。

Privateでの安全な移送には、オーナー以外の共有がないことを事前確認した**一時Google Sheets**へ、既存コネクタで取得した値を型別リテラルとして移し、XLSXへ一度書き出す手法を使用。**一時Sheetは削除済み**。実資料や値を公開GitHub/CIへアップロードしていない。このステージングは本番機能ではなく、認証済み原本`FORMULA`レスポンスを保持してPrivate Pythonへ渡す**手動検証のための一時経路**であり、別のXLSX再変換による一般的な完全再現性を保証しない。

- 2資料2タブ、**商品候補44行／JAN候補14行／ASIN候補39行**、プライベートのJAN候補検索1ヒット。原本ハッシュ不変、商品同一性未確定、利益・発注不許可。
- 今回の原本FORMULA取得由来の数式文字列**28件**をPrivate Pythonでも保持。以前のネイティブSheets→Excel書き出しで得た同範囲を旧経路で取り出すと**0件**であった。双方とも商品候補の件数はこの限定窓では一致したが、価格/税区分/ロットの信頼性は確認していない。
- 混在入口の匿名集計に`formula_cells_in_supplied_sheet_windows`を追加。ユーザーに返してよいのは**数式セル件数のみ**。`formula_cell_values_not_evaluated=True`、`source_formula_fidelity_verified=False`を維持。**観測件数は外部コネクタの認証主体証明でも数式の正しさの証明でもない**。
- 追加で架空の数式を使う**2件の回帰テスト**を記載。GitHub Actionsでは公開開発コードと架空資料のみを検査。

詳細な匿名件数・原本差分の記録は非公開知識Repoの`suppliers/pilots/live-formula-mixed-e2e-2026-11-09.md`参照。

**残課題**：非公開実行環境で機密の元行と検索ヒットを**利用者だけに安全提示する仕組み**、複数社のJAN/ASIN/包装単位の検証、WIF/専用Readerを用いたGitHubからの認証済み自動アクセス、本番導入と課金レビュー。これらは今回有効化していない。
