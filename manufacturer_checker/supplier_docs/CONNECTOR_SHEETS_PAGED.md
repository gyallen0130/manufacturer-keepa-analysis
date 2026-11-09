# メーカーGoogle Sheetsの40行超オンデマンド検索（開発中）

更新：2026-11-09 JST ／ Draft PR #1・main未マージ

## 用途

従来の「Google Sheets 1～5タブ、各A1:O40まで」では40行目以降の商品を検索できないため、認証済みのChatGPT/Google Driveコネクタから複数の連続した範囲を読み、**元のGoogle Sheetsの物理行番号を維持する限定ページ検索**を追加する。

新規Pythonモジュール：[connector_sheets_paged.py](connector_sheets_paged.py)

- 匿名入口：`inspect_selected_connector_sheet_pages(manifest=..., search=...)`。候補行数・数式文字列数・検索ヒット件数など**匿名集計のみ**。
- 本人限定詳細入口：`inspect_selected_connector_sheet_pages_for_review(manifest=..., search=..., reviewer_context=...)`。既存の`private_hit_review.py`を利用し、原本シート・物理行番号・JAN/ASIN候補・商品名と、**接続元が実際に確認したgidがある場合だけ**行へのリンクをPrivateで返す。
- 同一資料のヘッダーを各ページ先頭にPrivate内部で再付加して共通パーサーに通し、行番号・各行の警告を元の物理行へ再対応付けする。
- 各ページで**識別子の列マッピングが変われば停止**。見出しのない利益区分コメントの推定だけは、**検索にもPrivate表示にも使わない**のでページ間の違いを許容。これをもって利益判断を行わない。

## 必須のGoogle接続元での手順

1. ユーザーが選択したファイルへの**実際の閲覧権限**を認証済みDrive接続で確認。Google Sheetsのメタデータから、**表示中の実タブ名・sheetId（gid）・行／列数**を確認。
2. タブ内の見出しを確認（今回の方式では見出し行は1～20行目のいずれか）。ヘッダーが元の第H行なら、**`A1:O<H>`をFORMULA形式で取得**。`header_rows`には、元の1～H行をそのまま指定し、`header_row=H`。
3. データ部分は、明示した連続範囲を個別に取得する。H=1の例：**`A2:O40`と`A41:O79`**、H=14の例：**`A15:O40`と`A41:O66`**。常に原本の開始行と終了行を`start_row`/`end_row`へ正確に渡す。各レンジの取得は`value_render_option=FORMULA`。
4. Googleのレスポンスで末尾の空白行が省略された場合、要求済み範囲の空欄だけを空欄としてPrivateで復元する。**レスポンスが短いだけで、その後の行まで存在しないと判断しない**。
5. 既存の認可済み本人セッションから匿名検索を行い、必要に応じて本人限定詳細入口を呼ぶ。**このPythonコードに利用者認証機能はない**。`reviewer_context`は認証済み呼出元がチェックを実施した旨の宣言でしかない。
6. 検索が0件でも、検索済みページ以外に該当商品がないとは断定しない。`all_rows_in_selected_tabs_searched=False`、`all_supplier_folders_searched=False`を常に維持。

### 架空データによる使用例

```python
from supplier_docs.connector_sheets_paged import (
    SCHEMA_VERSION, MODE,
    inspect_selected_connector_sheet_pages,
)

manifest = {
    "schema_version": SCHEMA_VERSION,
    "mode": MODE,
    "sources": [{
        "spreadsheet_id": "SYNTHETIC_SHEET_A_001",
        "sheet_name": "架空見積",
        "document_type": "quote_request",
        "snapshot_method": "connector_formula_values",
        "header_row": 1,
        "header_rows": [["商品名", "JAN", "ASIN"]],
        "pages": [
            {
                "start_row": 2,
                "end_row": 40,
                "rows": [["架空商品", "0000000000017", "B0TEST0001"]],
            },
            {
                "start_row": 41,
                "end_row": 79,
                "rows": [["架空の41行目商品", "0000000000017", "B0TEST0001"]],
            },
        ],
    }],
}
summary = inspect_selected_connector_sheet_pages(
    manifest=manifest, search={"field": "jan", "query": "0000000000017"})
# summaryだけ匿名集計として使用。元JAN・商品名・原本URLは出ない。
```

## 制約・安全基準

- **選択1～5タブ、最大5ページ／呼出し、ページごと「見出しを含めて」40行以内、データ範囲最大合計200行、各15列まで**。現行では先頭からの連続した範囲のみを受け付ける。意図しない途中ページの欠落、重複、1行のずれ、複合型セル、過大テキスト、未承認のキーは拒否する。
- 複数ページで見出し位置は変えない。元のデータページ範囲は**必ず`header_row+1`から連続**。元のヘッダー行を各ページのデータ行として誤認しない。
- `parse_rows`の見出しが同じでも、ページによって**ASIN等の暗黙推定列が変わる場合は停止**。利益コメント列だけの推定差は受理しても価格／税／利益を出力しない。
- `FORMULA`で取得した文字列を実行・再計算しない。数式セル件数は元のヘッダーを二重計上せず、各元ページのセルを一度だけ集計する。
- 選択した行までの検索は検証できるが、40行超の**全1,000行・112社を自動的に走査できるシステムではない**。未選択タブ・残りの行・権限外データは対象外。
- `native_export_xlsx`経路では原価・数式忠実性を保証しない。全経路`purchase_allowed=False`、`profit_calculation_allowed=False`、`source_writes=0`。
- **追加のGoogle API呼出しはこのPythonモジュール内では行わない**。実際の呼出し回数は外部のChatGPT/Driveコネクタ側に発生するため、`api_calls=0`はネットワーク通信がないことの全体保証ではない。Google OAuthトークンやサービスアカウント鍵をPythonへ渡さない。

## 実資料での限定検証（匿名集計）

2026-11-09、権限確認済みの**2社・2タブ**で`A1:O1`、`A2:O40`、`A41:O79`を各々FORMULA指定でPrivate取得し、**計4データページ**を共通Pythonコードに投入。

- 合計**データ範囲156行を要求**。実行で確認した**商品候補107行**、**数式文字列96件**、追加資料への書込みなし。
- 1つの原本Sheetでは**41～79行目の39商品候補**を抽出し、後半のASIN候補に対する検索で**後半行ヒットと原本gid行リンクが一致**。
- 別の原本Sheetは2ページ目が空であり、**49行をレスポンス未返却の空白として補完**（第1ページ末尾10行＋第2ページ39行）。この有限範囲を越えた不在は証明しない。
- Privateのデータ／識別子／価格／Excelコピーは**公開GitHubへアップロードせず**、所有者限定の一時Google Sheetsに文字列式を安全に保持してPrivate Pythonへ渡した。**一時Google Sheetsは削除済み**。実原本は読取のみ、移送先コピーのハッシュは前後同一。
- テストで明らかになった、ページ間の**非検索用途の利益ラベル推定差**を許容する最小改修を行い、逆に識別子列の推定差は拒否する回帰テストを追加。
- 2026-11-09のGitHub Actionsでは**666件の架空データ中心のPythonテスト・3検証ジョブがすべて成功**。公開CIには実商品を一切渡さない。

## 残タスク

1. ChatGPT認証済みの呼出元から本ページングを**任意の指定取引先に対して持続的に起動・本人に結果を表示**できるアプリ/運用アダプター。今回はPrivate Pythonの実データE2Eまで。
2. より長い資料の安全な次ページ繰返し、検索済み範囲の明示、選択した複数資料の更新差分チェック。現状は1回最大5ページ。
3. GitHub Actions→Google WIF→Readerの**実認証**、アクセス権・費用・機密の保持期間・本番設定のレビュー。追加有料サービス、IAM/Secrets、Claudeは導入しない。
