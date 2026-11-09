# 取引先名＋JAN/ASINから一括オンデマンド検索（開発Draft PR、未本番化）

更新日：2026-11-09 JST

## 実装した一括実行部品

`supplier_lookup_session.py` の `run_supplier_lookup_once()` は、これまで個別だった次の処理を**1つのPython呼出し**にまとめる。

1. 認証済みアプリが事前に確認したPrivateタブメタデータから、取引先名を一意に解決（`supplier_query_planner.plan_supplier_sheet_reads`）。
2. 選択したファイル・可視タブ・見出し行に対して、**最大5データページ（1〜5タブに配分）**とヘッダー読取範囲を計画。1タブで見出し1行なら`A1:O1`＋`A2:O40`〜`A158:O196`の**最大195データ行**。
3. 認証済みアプリが注入した**読み取り専用コールバック**`fetch_formula_range`を、各計画範囲に対して`value_render_option='FORMULA'`を付けて呼出す。
4. 各レスポンスの**ファイルID・シート名・要求範囲・レンダリング指定**が期待値に一致することを検証。取得APIエラーは秘密を含み得るため一般化した例外で停止し、**空白データとして継続しない**。ファイル違い・タブ違い・範囲違い・余分な属性は拒否。
5. `supplier_query_planner.build_private_page_manifest`で取得済み行列と実物理行を結びつけ、`connector_sheets_paged`で商品候補を検索。
6. **通常は匿名集計だけ返す**。`include_private_hits=True`かつ本人アクセスの独立確認を外部で済ませた場合だけ、既存のPrivate閲覧機能から候補商品名・JAN/ASIN・原本行位置を返す（最大20件、打切り明示）。

### 使い方（架空データの模式例）

```python
from supplier_docs.supplier_lookup_session import run_supplier_lookup_once

def approved_drive_fetch(*, spreadsheet_id, sheet_name,
                         requested_range, value_render_option):
    # 呼出元の認証済みGoogle Drive APIの結果を使用する。
    # 成功時のみ、以下の5キーが正確な辞書を返す。
    # Google APIエラー時は例外を投げ、空行に置き換えない。
    return {
        "spreadsheet_id": spreadsheet_id,
        "sheet_name": sheet_name,
        "requested_range": requested_range,
        "value_render_option": value_render_option,
        "rows": previously_authorized_rows,
    }

result = run_supplier_lookup_once(
    supplier_query="架空の仕入先",
    search={"field": "asin", "query": "B0TEST0001"},
    approved_tab_metadata=previously_verified_private_tab_metadata,
    fetch_formula_range=approved_drive_fetch,
)
# このままでは「previously_authorized_rows」等は未定義。
# これは認証済みアプリが実装するコールバックの契約例。
# 個別識別子やファイルIDがない匿名結果のみ通常表示する。
```

**警告**：このモジュールはGoogle OAuth、IAM、本人認証、認可UIを実装しない。`approved_tab_metadata`にある`source_access_checked=True`やPrivate表示時の4つの真偽値は、**呼出元アプリが認証済みユーザーの実権限を既に確認したという宣言**でしかない。任意の利用者がこのPython関数を呼べる公開APIに配置してはならない。将来Claudeを導入する場合も特定モデルSDKに依存しないこの契約を再利用できるが、Claude本体は未導入。

### セキュリティ・整合性

- 取得ファイルID・取引先名・検索JAN/ASIN・商品名・ページの行列・原本リンクは**PRIVATE**。GitHub/CIや共有ログへ保存しない。
- **公開可能**：`public_summary`、`public_search_summary`、`coverage`の匿名件数・範囲に関する集計だけ。`private_review`は一切公開しない。
- 同一Googleファイル内に複数のタブがあり、URLだけのgid対応では曖昧になる場合、**間違ったタブの直接行URLを作らず無効化**する。タブ名・行番号のPRIVATE表示は保持。
- 任意のタブやフォルダを自動発見しない。実ファイルの権限確認、metadata取得と各Range読取は接続元アプリの責任。
- `grid_rows`は物理グリッド容量であり商品行が存在する証明ではない。結果が0件でも対象の残り行・他社・別タブで商品がないとは主張しない。
- 数値型JAN・ASIN候補・商品販売単位は**未確認候補**であり、仕入れ・原価・利益・発注判断を許可しない。
- 外部のコールバックが真実を返すこと自体をこのPythonコードは暗号的に証明できない。**ホスト側の信頼済みコネクタ、本人セッション、レスポンス原本との突合が必須**。

## 2026-11-09 テスト

- 新規`test_supplier_lookup_session.py`の**架空17テスト**：取引先一意選択、正しい範囲／FORMULA、41行目ヒット、PRIVATEリンク、匿名秘密保護、未承認・曖昧取引先のコールバック未呼出し、Private表示未許可の先行拒否、APIエラー時の秘密情報非表示、レンダリング方式・ファイル・範囲のすり替え拒否、複数タブ同一ファイル時の誤gidリンク拒否、0件・空行・入力不変。
- GitHub Actionsの全回帰テストは**700件**。公開CIは架空の商品／ファイルIDしか使っていない。

### 実Google Sheets由来のPrivate E2E

以前から承認済みの**株式会社井上「見積もり」**の可視タブ・gid・グリッドサイズを既存ChatGPT Google Driveコネクタで読み直し、`A1:O1`および5つのデータ範囲`A2:O40`、`A41:O79`、`A80:O118`、`A119:O157`、`A158:O196`を**すべて`FORMULA`で実取得**。所有者限定の一時Google Sheetsを介してPrivate Python実行環境へ文字列・数値を保持して転送し、**一時Google Sheetsは削除済み**。

現行GitHub開発ブランチの11依存モジュール＋新しい`supplier_lookup_session.py`の**実コード12ファイル**をPrivate Pythonで直接読み込み、一時保存した実資料スナップショットを**読取専用コールバックとして再生**。結果は：

- **原本195データ行を解析**、元Google Sheetsの**数式文字列84件を保持**。
- 41行目より後に実在する**ASIN候補1件を使って検索**し、**1ヒット**。原本の物理行番号・確認済みgidによる正しい行リンクをPrivateの戻り値で突合。
- 呼出した範囲はヘッダー1件＋データ5件の**合計6範囲**で計画と完全一致。
- 匿名集計に元ファイルIDや実ASINを含まない。PRIVATE結果にも価格を含まず、原本と受渡し用のローカルファイルのSHA-256は実行前後一致。
- **検証の境界**：Googleの実API呼出しはChatGPTの認証済みコネクタが**先に**実行。その値を隔離Pythonコールバックが再生した。これは「Googleで認証して取得したPrivate値→GitHub上の現行共通Pythonで1コール検索」のE2Eであり、**任意のChatGPTチャットから直接Pythonを自動呼出しする恒常的アプリ接続**やGitHub ActionsからGoogleへのWIF認証成功を示すものではない。

## 残る次工程

1. ChatGPT/Driveに備わる認証済みコネクタ呼出しを、都度手動でPrivate Pythonへ転送せずに扱える**継続利用可能な実行アダプター**（チャット上の本人限定表示や権限の厳密な継承）を検討。ChatGPT Workや独自拡張が必要になる場合は利用可能な既存機能・費用を先に確認。
2. **200行以上の続きの行位置、検索済み範囲、原本更新時の安全停止**を記録する再開可能な検索構造を設計。接続元の認証や機密保持は常に独立。
3. 112社の索引を確認・利用し、対象取引先と必要タブを漏れなく安全選択する。全フォルダを無制限巡回しない。
4. GitHub Actions→Google WIF→専用Readerの実認証と本番稼働は、費用・IAM・Secretsと原本アクセス権を検証した後に別段階で行う。

追加有料サービス、IAM/Secrets、既存GitHub本番Workflow、Amazon運用環境、Claude接続は今回変更していない。
