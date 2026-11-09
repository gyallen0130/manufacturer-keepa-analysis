# メーカーGoogle Sheetsの200行超・安全な継続検索（開発中）

更新：2026-11-09 JST / Draft PR #1 / 本番未反映

## 目的・今回の変更
Google Drive上のメーカー見積書や商品一覧が200行を超える場合、すべての行を一度に読み込まず、**1回最大5データページ、1ページにヘッダーを含め40行以内**で検索を繰返す。元のGoogle Sheets物理行番号を保持し、前回と同じ行の二重計上を防ぐ。

- [connector_sheets_paged.py](connector_sheets_paged.py) の既存の解析機能を拡張し、**Private入力の `data_start_row`** を明示できるようにした。未指定の場合は従来どおりヘッダー直後から始めるため既存呼出しとの後方互換性を維持。
- 新規 [supplier_scan_continuation.py](supplier_scan_continuation.py) は `scan_next_selected_supplier_sheet(...)` で、最初のバッチまたはPrivateカーソルからの次バッチを読む。今は**本人が承認したGoogle Sheets 1タブのみ**を対象にする。複数タブを黙って先頭1つに省略しない。
- 標準見出し（1行目）の場合、1回目 `A2:O40`〜`A158:O196`、2回目は**`A197:O235`〜`A353:O391`**。14行目ヘッダーの場合、1ページ26データ行になり、原本行番号は正しく補正される。
- 次回位置 `next_row`、累計検査データ行数、累計検索ヒット**下限数**、打切りフラグ、対象タブのグリッド終端到達有無をPrivateカーソルに保存。データやJAN/ASINそのものをカーソルに入れない。ただしカーソルのハッシュは類推可能なので**Privateのみ**。
- `public_scan_progress()` は**匿名の件数・進捗だけ**に絞って表示する関数。Privateカーソル・取引先名・ファイルID・商品情報・値を公開GitHub、公開CI、共有ログへ出さない。
- 商品がヒットした場合、本人専用Private結果で商品名・JAN/ASIN候補・元タブの物理行番号・**確認済みgidの原本リンク**を返せる。商品同一性、利益、仕入可否は断定しない。

## 再開前の必須検査
**このPythonコードはOAuthやGoogle Drive本人認証を行わない。** 利用者の本人確認、原本ファイルへの今のアクセス権限、Googleシートの可視タブの確認は呼出元が必ず行う。任意の一般利用者がこの関数を呼べる公開サービスに設置しない。

入力アダプターは両方必須：
- `fetch_formula_range(spreadsheet_id, sheet_name, requested_range, value_render_option='FORMULA')`：本人が認証した読み取り専用Google Drive接続が**実際に取得**した結果を、正しいファイル／タブ／レンジ／`FORMULA`付きの5キーで返す。API失敗時は例外、**空配列にして続けてはならない**。
- `get_source_revision(spreadsheet_id)`：**元ファイルの変更を検知できる十分に信頼できる版識別子**を `{'spreadsheet_id':..., 'revision':'opaque-revision'}` で返す。ファイルIDが合わない、値が不正、版が変わった場合は検索停止。実データ／認証情報を返さない。信頼できる変更検知トークンがない場合は**バッチまたぎの検索を本番運用しない**。

最初のバッチでは版識別子を読取前後で照合し、ヘッダーと最終物理行のSHA-256指紋をPrivateカーソルに保持する。2回目以降は**原本ファイル・gid・元タブ・グリッド行数・ヘッダー行・検索条件が同じ**か確認したあと、前回の版情報を再検査。ヘッダーを再読込し、**直前バッチ最後の物理行を再取得**して指紋が同じか検査する。全ページ読み終わった後に版情報を再取得して差異があればバッチ全体を破棄する。

**安全性の限界**：SHA-256のヘッダー／境界行検査だけでは、以前の範囲の任意の行を編集されても全て検知できない。信頼できる**単調増加のDriveファイル版番号など**が必要。ChatGPTの現在のDriveメタデータコネクタで取得できる `modified_time` は**参考時刻**であり、コンテンツ変更を確実に証明する単調増加版番号と同一とは扱わない。今回のPythonコードは、呼出元の版トークンを比較するだけで、版トークンの信頼性・Google認証を単独で検証しない。Privateカーソルも署名された認可証明ではないため、認証済みPrivate環境で保持し、一般ユーザーから任意に入力させない。

## 呼出しの考え方（完全に架空の資料・識別子）
```python
from supplier_docs.supplier_scan_continuation import (
    scan_next_selected_supplier_sheet, public_scan_progress
)
# approved_metadata: 認証済みGoogle Driveで今確認したPRIVATEのタブ情報
# authenticated_formula_reader: 同一セッションの実FORMULA取得アダプター
# authenticated_revision_reader: 原本改変を検知できる確かな版情報
first = scan_next_selected_supplier_sheet(
    supplier_query="架空卸A",
    search={"field": "jan", "query": "0000000000017"},
    approved_tab_metadata=approved_metadata,
    fetch_formula_range=authenticated_formula_reader,
    get_source_revision=authenticated_revision_reader,
)
safe_progress = public_scan_progress(first)  # 公開可能な匿名集計
# first全体はPRIVATE。中のprivate_cursorを公開したりGitHubへ保存しない。
second = scan_next_selected_supplier_sheet(
    supplier_query="架空卸A",
    search={"field": "jan", "query": "0000000000017"},
    approved_tab_metadata=approved_metadata,  # 毎回、再検証された情報
    fetch_formula_range=authenticated_formula_reader,
    get_source_revision=authenticated_revision_reader,
    private_cursor=first["private_cursor"],
)
```
※上記の認証済みアダプター3変数は**説明用の未定義オブジェクト**。コードだけで実運用認証まで完了したという意味ではない。

## 回帰テストと現時点の実資料検査（2026-11-09）
- 架空の500行の資料で**3バッチ**を実行。1回目2～196行、2回目197～391行（220行目にヒットしてgidリンク生成）、3回目392～500行。元行重複なし、データ行499件で終了。途中で検索条件、原本情報、版情報、ヘッダー、境界行が変わると停止する。
- 架空の14行目ヘッダー、式セルの未実行・件数、同一ファイル複数タブの拒否、不正コールバック、Private表示未許可時の読取前停止、公開集計に実商品が混入しないこと等を**17件の新規テスト**で確認。
- GitHub Actions：**717 tests / OK**、`offline-tests`、`container-dry-run`、`windows-local-backup-tests`の3ジョブ完了。
- 井上の実Google Sheets「見積もり」のメタデータが取得可能であり、Google Driveの`modified_time`が取得できることを確認。認証済み読取の `FORMULA` で**A196:O196、A197:O235、A236:O274、A275:O313**を安全な上限内で確認。**第1データページ39非空行・第2ページ20非空行・第3ページ0非空行**、前後の`modified_time`は一致。原本を変更していない。これは**実範囲の読取確認**であり、**今回の新しい継続スキャナに実データを投入した完全E2Eではない**。Google Driveの強い版保証も未確定。

## 次の工程（未完了）
1. 認証済みChatGPT/Drive等のホストが保証できる**原本版番号の取得可否と改変時の更新保証**を検証し、単なる`modified_time`で足りない場合は確実な版識別を提供できる接続方法を設計。
2. ChatGPTからPrivateカーソルを安全に維持し、次ページを呼び出せる**恒常的な認証付きアダプター／UI**。現状は読み取った行をPrivateメモリで処理する試作。
3. 複数の選択タブと112社への対象管理を段階的に拡張。**全社全タブの検索完了、在庫・原価・仕入判断は未実装**。
4. GitHub Actions→Google WIF→Readerの実認証は、コスト・権限・IAMレビュー後に実施する。新有料サービス、Secrets、IAM、本番Actionsはこの工程で触らない。
