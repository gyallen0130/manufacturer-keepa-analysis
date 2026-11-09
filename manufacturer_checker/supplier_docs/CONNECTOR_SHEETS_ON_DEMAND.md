# ChatGPT接続済みDriveからメーカー資料をオンデマンド検索（Sheetsだけでも可）

更新: 2026-11-09 JST / 開発Draft PR #1、main未マージ

## 対象と目的

`connector_sheets_on_demand.py` を追加。以前の`connector_mixed_one_shot.py`は**ExcelとGoogle Sheetsの両方**が必要だったが、今回の入口では**認証済みChatGPT/Driveコネクタから指定したGoogle Sheets 1〜5タブのみ**で、JAN・ASIN・商品名・型番などを検索できる。

- **匿名入口**：`inspect_selected_connector_sheets(connector_sheet_manifest=...,search=...)`。返り値は検索対象範囲、匿名の候補件数、見出し状態、数式セル数などだけ。JANや実商品名・原本URLは含まない。
- **利用者限定の詳細入口**：`inspect_selected_connector_sheets_for_review(...,reviewer_context=...)`。接続元がファイルの閲覧権・本人限定表示先・閲覧操作を**実際に独立確認した場合のみ**、Privateで商品名・JAN/ASIN候補・元タブ/行・原本リンクを表示するためのデータを組み立てる。
- **Excelとの混在**：従来の`connector_mixed_one_shot.py`をそのまま使用。既存APIと匿名既定値の後方互換性を保持。
- **大切な制限**：このPythonコードは**認証・本人確認・認可を実行しない**。呼出元が設定した`reviewer_context`の4個の真偽値は本人確認の証拠にならず、呼出元アプリの実認証が別途必要。商品行や非公開結果をGitHub・CI・共有ログ・メールへ出さない。

## 実行手順（ChatGPT側が必要な操作）

1. Private GitHub共通知識`suppliers/index.md`の取引先・原本索引からユーザーの指定メーカー資料を特定する。ユーザーがまだ指定していなければ用途に合う**最大5タブ**を選択する。すべて検索したかのように断定しない。
2. ChatGPTに接続済みのGoogle Driveで原本ファイルの**閲覧可能性**を確認。`get_spreadsheet_metadata`により**存在する可視タブ名・sheetId(gid)・行列数**を実取得する。Excel原本は別の既存Privateアダプターへ。Sheetのみならこの新入口を使う。
3. 各Sheetの明示選択した**A1:O40**を`get_spreadsheet_range`の`value_render_option=FORMULA`で読む。セルの数式文字列は**評価しない**。取得した実セル行列を**PRIVATE実行環境のメモリだけ**でマニフェストにする。元のOAuthトークンは渡さない。
4. **匿名検索**を先に行い、検索対象の範囲、何件ヒットしたか、要確認対象数を検査する。未取得値や0件を「該当商品なし（全社）」と扱わない。
5. 利用者本人が詳細閲覧を求め、認証済みのUI/呼出元がアクセス権と結果の本人向け表示を実際に確認できた場合に**限り**、Private詳細入口を呼ぶ。`sheet_gid_by_url`は認証済みメタデータで確認済みの **`{original_sheet_url: actual_gid}`** のみ設定し、元の行へジャンプするURLを本人専用画面で表示する。対象範囲やgidを推測してはいけない。
6. 調べる商品が最大40行の外、または対象外タブにある場合は、**検索対象範囲不足**と明示する。範囲拡大・次ページ選択は別作業、全112社自動巡回は未完成。

## 非機密の利用例（実行用の雛形）

```python
from supplier_docs.connector_sheet_snapshot import SCHEMA_VERSION, MODE
from supplier_docs.connector_sheets_on_demand import (
    inspect_selected_connector_sheets,
    inspect_selected_connector_sheets_for_review,
)

# ここは架空の行とファイルID。実値は認証済みのDriveコネクタで取得し
# その同じ利用者の非公開メモリ内にだけ持つ。公開ログには出さない。
approved_snapshot = {
    'schema_version': SCHEMA_VERSION, 'mode': MODE,
    'sources': [{
        'spreadsheet_id':'SYNTHETIC_SHEET_A_001',
        'sheet_name':'架空見積',
        'document_type':'quote_request',
        'snapshot_method':'connector_formula_values',
        'rows':[['商品名','JAN','ASIN'],
                ['架空商品','0000000000017','B0TEST0001']],
    }],
}
search = {'field':'jan','query':'0000000000017'}
public = inspect_selected_connector_sheets(
    connector_sheet_manifest=approved_snapshot, search=search)
# publicだけ匿名件数のログへの利用が可能。
# 認証済みアプリの利用者本人が明示的に要求した場合だけ:
private = inspect_selected_connector_sheets_for_review(
    connector_sheet_manifest=approved_snapshot, search=search,
    reviewer_context={
        'source_access_checked':True,
        'private_recipient_checked':True,
        'private_display_requested':True,
        'no_public_logging':True,
    },
    # 実接続から確認したgid以外を与えてはならない。
    sheet_gid_by_url=None,
)
# privateは個別商品名を含むので絶対にprint/log/保存/共有しない。
```

**注意**：上記の4つのTrueは**認証の代わりではない**。このPython関数を任意の外部利用者が呼べる公開APIとして配置してはならない。

## 2026-11-09の実資料E2E（匿名統計）

ChatGPTに接続済みGoogle Driveで**井上「見積もり」**と**ワコーフーズ「見積もりリスト」**の可視性とgidを確認した。両方を`FORMULA`モードで限定取得し、原本データを公開Repoへ渡さず、一時的な所有者専用Private Pythonに受け渡した。使用したPrivate転送Sheetは削除済み。

- 2社・2タブ（A1:O40の各窓）、**商品候補68行、数式リテラル57件**（元Googleコネクタで井上28、ワコーフーズ29）。
- **両タブの見出しがparsed**。各社から実データに含まれるASIN候補を1つずつPrivateで選択し、同じ新Python入口で別々に検索。**それぞれ1件ヒット、元タブ/元物理行/GID基準リンク生成に成功**。
- 匿名入口に個別JAN/ASIN・元URL・商品名なし。Private結果にも元仕入価格・数式値なし。認証や資格情報・元ファイルを書換えていない。
- **これは選択2社のA1:O40の有限検索**。2社の商品が一致したとは主張しない。JANが数値型で先頭0が失われた可能性や販売単位の違いは未確認。原価・利益・発注判断禁止。
- GitHub Actionsの架空データだけを使う**15件の新規テスト**と既存回帰試験は、`offline-tests`、`container-dry-run`、`windows-local-backup-tests`の3ジョブで成功。課金を増やすサービス・OAuthトークン・Google IAM・GitHub本番Workflow設定は変更していない。

## 完了していない部分

- **ChatGPT標準UIから任意のGitHub Pythonコードを自動起動する正式な永続接続**、本人限定のクリック操作画面、認証付きの一括検索プロダクト化。現時点は人が実行を指示する手動オンデマンドMVP。
- 検索対象の112社への自動拡張、40行を超える資料へのページング／差分更新、Google Drive原本に紐づく永続プライベート検索インデックス。
- GitHub Actions→Google WIF→専用Readerの**本当の実認証**。既存Google Drive共有があることはGitHub側の実認証成功を意味しない。
- 将来Claudeを追加してもPython APIを再利用可能にする設計とするが、Claudeサービスそのものはまだ導入しない。
