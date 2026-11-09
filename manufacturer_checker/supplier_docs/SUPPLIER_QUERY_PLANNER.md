# ChatGPTから取引先名でGoogle Sheets検索を始めるための読取計画

更新：2026-11-09（開発中／Draft PR #1／main未マージ）

## この工程の目的

ユーザーが「取引先AのJANを調べて」「取引先BのASINを検索して」などと指定した際、**GitHub内の共通Python機能**が、既に認証済みChatGPT Google Drive接続で確認・選択した取引先の**ファイル・タブ・読取範囲**を計画する。

従来は範囲の選択を人が手順書から計算していた。今回の`supplier_query_planner.py`は、認証済みコネクタから取得済みの**PRIVATEタブメタデータ**を受け、次の2段階を実装する。

1. `plan_supplier_sheet_reads(...)`：明示的な取引先名に一致するタブだけを選び、最大5ページの`FORMULA`読取範囲をPRIVATEに計画。
2. `build_private_page_manifest(...)`：外部ChatGPT/Driveコネクタが実際に取得した結果を、**選択済みファイルID・正しいタブ名・厳密な範囲**と突き合わせ、旧`connector_sheets_paged.py`が利用できる入力へ変換。

**本人認証とGoogle Driveアクセス権の確認は、これらの関数自身ではできない**。呼出元は、ユーザーの認証済みセッションで**現在選択したGoogleファイルの閲覧権と表示タブを実際に検証**する必要がある。`source_access_checked=True`等の値は**外部検証済みという自己申告であり、認可の証明ではない**。このモジュールを公開APIにしてはいけない。

## 入力するメタデータ

`approved_tab_metadata`は**元のDrive索引からユーザーが選んだ取引先の候補**と、その候補に対して**認証済みのコネクタで今取得したメタデータ**を合成した、PRIVATEの配列。会社名をファイル名やタブ名から推測しない。

各要素は次のキーのみ使用する。

| キー | 内容 | 確認元 |
| --- | --- | --- |
| `supplier_label` | 明示的に索引で対応付けられた取引先名 | Privateの取引先索引 |
| `spreadsheet_id` | 実Google SheetファイルID | Drive検索・メタデータ |
| `sheet_name` | 目視確認した可視タブの正確な名前 | `get_spreadsheet_metadata` |
| `sheet_gid` | タブの実`sheetId`（行リンクに利用） | 同上 |
| `grid_rows`／`grid_columns` | 元タブの物理グリッド行数・列数 | 同上 |
| `header_row` | 1〜20の実見出し物理行番号 | 認証済みの見出し`FORMULA`セル検査 |
| `document_type` | `quote_request`等の明示資料分類 | 承認済みPrivate索引 |
| `visible` | 実メタデータで可視 | 呼出元の実確認結果 |
| `source_access_checked` | 現在の本人セッションで閲覧を実確認済みという宣言 | 呼出元アプリ |

**重要：`grid_rows`はシートの容量であり、商品が存在する最終行を表さない。** 頭から195行を計画しても、実データが39行までなら残りが空でも、さらに他タブ・ほかの取引先を調べたことにはならない。

## 取引先名のマッチング

- 最初にNFKC正規化した**完全一致**で検索する。
- 完全一致がない場合、**部分一致が1社のみ**なら採用する。例：「架空の井上商会」に対する「井上」。
- 部分一致が0件、2社以上なら停止する。表示可能な候補を勝手に最初の1社へ絞らない。
- 同一社でも対象が5タブを超える場合は停止する。候補をあらためて限定する。**見積情報を気付かないうちに欠落させない**。
- 候補カタログの上限は160タブ。これは全112社の無人列挙の実装ではない。呼出元のPrivate索引で**対象取引先の候補を限定**して渡す。

## 読取計画と実Google Sheets API呼出し

`plan_supplier_sheet_reads`の戻り値は**PRIVATE**。ファイルID・取引先名・タブ名・gidを含むため、公開CIやGitHubへ出力しない。

- 原本見出しが1行目なら、最初の範囲は`A1:O1`（ヘッダー）、`A2:O40`、`A41:O79`、`A80:O118`…。
- 見出しが14行目なら、`A1:O14`、`A15:O40`、`A41:O66`…。
- 読み取るデータは**最大5ページ**・1ページあたり見出しを含む40行以内・合計最大200データ行・15列まで。
- 複数タブは**ラウンドロビン**で1ページずつ割り振り、先頭タブに予算を使い切って2番目のタブを忘れるのを防止。
- 読取の際は認証済みの`get_spreadsheet_range`等を使い、**必ず`value_render_option=FORMULA`**。これは呼出元の責任で、このPythonモジュールはGoogleへ接続しない。
- ページの結果の`rows`が短い場合は、**取得に成功した正しい範囲の末尾空白**のみパーサー側で埋める。API失敗・権限エラーを空白応答に置き換えてはならない。
- 不明なタブ名・古いファイルID・要求していない範囲・二重取得・余分な件数・未知のキーや複合型セルは拒否。
- 一度に最大5ページしか計画しないため、全件検索や完全な在庫網羅を主張しない。

## 利用例（架空の識別子・資料）

```python
from supplier_docs.supplier_query_planner import (
    plan_supplier_sheet_reads,
    build_private_page_manifest,
    summarize_plan_without_private_sources,
)
from supplier_docs.connector_sheets_paged import (
    inspect_selected_connector_sheet_pages,
)

# このapprovedメタデータは、認証済みGoogle Drive接続を経由して
# PRIVATEに取得・照合する。例はすべて架空。
approved = [{
    "supplier_label": "架空の井上商会",
    "spreadsheet_id": "SYNTHETIC_SHEET_A_001",
    "sheet_name": "見積もり",
    "sheet_gid": 0,
    "grid_rows": 998,
    "grid_columns": 30,
    "header_row": 1,
    "document_type": "quote_request",
    "visible": True,
    "source_access_checked": True,
}]
plan = plan_supplier_sheet_reads(
    supplier_query="井上", approved_tab_metadata=approved)
# 個別ファイルIDを含むplanをprint/log/GitHub保存しない。

# ここでChatGPTコネクタがplan内のヘッダーと各data_pagesの
# requested_rangeを1回ずつFORMULAで読み取り、権限・API成功を確認。
# 以下のresponsesは実際のコネクタが取ってきた行配列を意味する。
# responsesの各要素はspreadsheet_id、sheet_name、
# requested_range、rowsの4キーに限定する。
paged_manifest = build_private_page_manifest(
    plan=plan, connector_responses=responses)

anonymous = inspect_selected_connector_sheet_pages(
    manifest=paged_manifest,
    search={"field":"jan","query":"0000000000017"})
# anonymousのみ匿名の集計値。実商品や取引先ファイルIDは含まない。
coverage = summarize_plan_without_private_sources(plan)
```

※上記のコードは呼出元が定義する`responses`を省略した説明用の雛形であり、単体での完成アプリやChatGPT標準UIのメニューを意味しない。

## 2026-11-09 検証結果

**GitHub Actions**：新規17件の架空データテストを追加。実施対象は取引先名の完全／一意部分一致・曖昧名拒否、未確認／不可視タブ拒否、5タブ・5ページ上限、1行/14行ヘッダー、複数タブの公平な範囲計画、レスポンスのファイル・タブ・範囲突合、欠落／重複／余剰・不正セル拒否、原本行41の連動Private検索、匿名集計の秘密非漏洩、入力不変。通信・実商品・認証情報は一切使用しない。

**実Google Driveメタデータ**：認証済みChatGPT Drive接続から、井上「見積もり」とワコーフーズ「見積もりリスト」の**実可視タブ・gid・グリッド行列数・見出し1行のFORMULA読み取り可否**を確認。その実メタデータを**現行GitHubソースを一時的に取り込んだPrivate Python**へ渡して、それぞれの取引先名から**正しい1タブだけ選択、5ページ・195データ行の計画（A2:O40、A41:O79など）**を生成・検査できた。匿名集計へファイルID等の機密が出ないことも確認。コード転送に用いた一時Google Sheetsは削除し、ローカル転送ファイルも削除済み。

**この実資料確認は「実メタデータ→読取計画生成」であり、計画した195行すべてを再取得・全件検索した試験ではない**。先に実施した井上・ワコーフーズのA1:O79実検索は別の[ページング実データE2E記録](CONNECTOR_SHEETS_PAGED.md)で確認済み。

## 残る工程

1. ChatGPTの本人セッションから、Drive索引→認証済みメタデータ→読取計画→外部コネクタ値取得→Private Python検索→本人限定表示を**永続的な1操作**にする実運用アダプター。現在は各コンポーネントを**手動で連携できる試作段階**。
2. 200行超の繰返しスキャンに備え、**検索済み範囲を秘密を含まない形で管理し、重複・欠損・原本更新によるズレを検知する継続トークン**。現在は先頭最大5ページで打切り。
3. GitHub Actions→Google WIF→専用Readerの実認証／本番ワークフロー。IAM・Secrets・課金の安全確認前に自動アクセス設定を変更しない。

**ChatGPTを優先**。Python関数は特定モデルのSDKに依存しないため将来Claudeを使う場合も再利用可能だが、Claude本体は導入しない。
