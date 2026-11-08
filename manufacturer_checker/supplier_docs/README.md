# 取引先資料の共通解析（試験版）

Google Driveのメーカー／卸問屋別フォルダにある見積書・商品リストの**表部分**を、出典・リスク付きの共通JSONに変換する試験版です。従来のKeepa分析・Colab実行・GitHub Actionsとは接続していません。

**対象**：.xlsx / .xlsm / .csv / .tsv と、Google Sheets v4の values.get が返す2次元配列。PDF解析、Driveの全フォルダ巡回、定期同期、Keepa照合、利益再計算、発注は未実装です。

## 使い方

既存コードと独立したモジュールです。APIキー不要のローカルファイル解析：

    cd manufacturer_checker
    pip install -r requirements.txt
    python -m supplier_docs.cli --input /path/to/quote.xlsx --sheet-name 見積もり --document-type quote_response

Google Sheetsを読み取る場合、**専用のサービスアカウントを鍵なしで代理認証**します。ログイン元のGoogleアカウント（ColabやCloud ShellのADC）は、専用アカウントへ一時的に代理認証できる必要があります。PythonコードからSheets APIへ渡すのは **`spreadsheets.readonly` だけの15分間の代理認証トークン**です。

### 最初に必要なGoogle Cloud設定（ユーザーによる操作）

1. 取引先資料用に、新規の専用サービスアカウント（例：`supplier-docs-reader@YOUR_PROJECT_ID.iam.gserviceaccount.com`）を作成する。**既存のSP-API用サービスアカウントや秘密鍵を流用しない**。
2. 同じCloudプロジェクトで **Google Sheets API** と **IAM Service Account Credentials API** を有効にする。
3. Colabでログインする本人のGoogleアカウントに、**この新規サービスアカウント単体だけ**の `roles/iam.serviceAccountTokenCreator` を付与する。プロジェクト全体には付与しない。
4. テストしたいGoogle Sheetsファイル**1件だけ**を、そのサービスアカウントのメールへ **閲覧者（Viewer）** で共有する。初回から取引先資料フォルダ全体は共有しない。
5. サービスアカウント鍵（JSON/PEM）は**作成しない**。認証の準備やユーザー承認ができるまでは接続試験を実行しない。

設定後、[Colabで安全な集計試験を開く](https://colab.research.google.com/github/gyallen0130/manufacturer-keepa-analysis/blob/feature/supplier-docs-normalizer-v1/notebooks/supplier_docs_readonly_smoke.ipynb) から手順に沿って実行できます。NotebookはPythonコードを検証済みコミットに固定して取得し、IDは非表示入力、結果は集計のみ表示します。ChatGPTのGoogle Driveプラグインから認証情報を取得することはできません。

同様に、Colabではなく**ユーザー自身の認証済みローカル環境**でCLIを実行する場合：

    python -m supplier_docs.cli --sheets-id YOUR_SHEET_ID --sheet-range "'見積もり'!A1:L40" --document-type quote_request --impersonate-service-account supplier-docs-reader@YOUR_PROJECT_ID.iam.gserviceaccount.com --summary-only

`--sheets-id` では専用アカウントの指定と `--summary-only` が**必須**です。ユーザーADCを暗黙に直接利用したり、取引先名や卸値などの生データをコンソール出力したりするモードは拒否します。

Google Workspaceでは、サービスアカウントのアドレスを対象シートの**共有先**としてViewerに指定できます。権限と共有設定の詳細は [Googleの公式説明](https://developers.google.com/workspace/guides/create-credentials)、鍵なし代理認証は [google-authの公式説明](https://googleapis.dev/python/google-auth/latest/reference/google.auth.impersonated_credentials.html) を参照してください。

document-type は manufacturer_list / quote_request / quote_response / catalog / price_revision から**原本の性質を確認して**選択してください。見積依頼を回答済み見積として扱わないため、自動推定しません。見出し行は先頭20行から推定し、必要なら --header-row 2 を指定します。対象の表範囲は原本に合わせて狭く指定してください。

## 複数シートの安全な取得（開発用アダプタ）

`supplier_docs.readers.sheets_visible_tabs` は、指定されたSpreadsheetの**表示中の通常シート**の名前だけをSheets APIのメタデータで取得します。非表示・オブジェクトシートは対象外です。

`supplier_docs.readers.sheets_selected_tabs_summary` は、呼び出し元が**タブ名と文書種別を明示したシートだけ**を指定行数・指定列まで読み込み、匿名の件数・注意コードを集計します。

- 文書種別はタブごとに指定が必要で、`manufacturer_list` / `quote_request` などの自動推測はしません。
- 既定は最大10タブ、タブあたり先頭40行・A:L列。合計50,000セルを超える指定を読み取り前に拒否します。
- 非表示・未指定・存在しないタブを勝手に読み込みません。見出しが判定できない場合は `needs_review` として扱います。
- 返すのはタブ順の番号・件数・リスクコード等だけです。タブ名、原価、JAN、ASIN、商品名、原本IDは集計結果に含めません。
- 現時点では**Pythonライブラリの開発用機能**です。既存のColab試運転やGitHub Actions本番ワークフローから自動実行するようには変更していません。実データでの複数シート一括実行は未検証です。

## Google Driveの更新差分検出（開発用、未接続）

`supplier_docs.drive_delta` に**メタデータだけ**を使った読み取り専用の差分検出部品を追加しました。Drive v3 の `files.list` で、利用者が明示的に許可したフォルダの**直下**だけを、ページ数・件数の上限付きで確認します。`name`（ファイル名）や原本の本文、共有権限は取得対象に含めません。

- `scan_approved_folder(service, folder_id=...)`: 1フォルダの完全なメタデータ一覧（ファイルID、MIMEタイプ、更新版番号／更新時刻）を、上限10ページ・500件で取得。**子フォルダは開かず**件数だけを集計。
- `scan_explicit_folder_set(service, folder_ids=[...])`: **承認済みIDを明示列挙**した複数フォルダを対象にする。既定上限は160フォルダ・240ページ・10,000項目。指定外のフォルダを探索したり、My Drive全体を検索したりしません。途中の失敗・取得漏れがあれば全体を不採用。
- `plan_changed_files(previous, current)` / `plan_explicit_folder_set(previous, current)`: 完全な2回分の一覧を比較し、初回は**基準点のみ**作成。2回目以降、新規・更新・不変・見えなくなったファイルを区別。アクセスが消えた／移動した可能性があるファイルは**削除せず要確認**とします。
- IDを含む一覧と作業候補は**機密情報**です。戻り値の `summary` だけを集計共有し、ID・フォルダ名・生のメタデータをGitHubや公開ログへ保存しないでください。
- まだスケジューラ、認証、永久保存、資料の実ダウンロードや自動解析とは**接続していません**。これらの関数は外部処理を自動起動しません。実資料への `files.list` 実行も未実施です。

**実運用前の追加条件**：現時点の専用サービスアカウントには *Google Sheets 2ファイルへのViewer共有* しかありません。Driveフォルダの巡回には所有者の明示的な許可が必要で、Drive APIの有効化、鍵なしの **Drive metadata readonly** スコープ（`https://www.googleapis.com/auth/drive.metadata.readonly`）と、**許可した対象フォルダの閲覧権限**を別途準備する必要があります。既存の `spreadsheets.readonly` だけではDriveのフォルダ一覧取得はできません。フォルダ全体を安易に共有せず、承認済みの対象範囲を明文化してから実装します。

## 差分スナップショットの暗号化保存と解析候補キュー（開発用）

`supplier_docs.snapshot_store` に、Drive一覧の**ファイルID・更新版番号をローカル暗号化して保存**する試験用モジュールを追加しました。用途はLinux/POSIX環境に限定しています。原本のコピーや仕入原価そのものは保存対象に含みません。

- `write_encrypted_inventory(path, key=..., snapshots=..., expected_revision=...)`: 呼び出し元が明示的に承認した一覧だけをFernetで暗号化し、所有者だけがアクセスできる0700ディレクトリに0600ファイルとして原子的に保存。新規保存は上書き禁止、更新には直前に取得した暗号文リビジョンが必要です。
- `read_encrypted_inventory(path, key=...)`: 暗号文の改ざん・復号失敗・危険な権限を拒否して、前回の一覧と照合用リビジョンを復元します。
- `review_queue(previous, current)`: 新規・更新ファイルだけを私的な確認キューへ振り分けます。Google Sheetsは閲覧専用解析の候補、Excel・CSV等のファイルは未実装の取得処理を要求する**手動確認候補**にします。ファイルID・フォルダIDはキュー内の機密情報であり、公開するのは集計欄のみです。
- `finalize_inventory(previous, current, completed_locations=..., reviewed_unavailable=...)`: 初回は `approve_initial_baseline=True` の明示的許可が必要です。2回目以降は**更新対象の全件処理と閲覧不可ファイルの確認が揃わない限り、基準点の更新を拒否**します。失敗時に古いスナップショットを保持して再試行できる設計です。

**運用上の重要事項**

- 暗号鍵は、別のアクセス管理されたSecret Managerなどで保持し、GitHubのコード・ノートブック・ログ・スナップショットと同じ保存場所には置かないでください。**鍵の発行・保管先・定期実行環境は未設定**であり、現時点では自動保存は稼働していません。
- 上記の関数は対象ファイルの自動ダウンロード・解析実行・仕入れ判断・発注を行いません。キューを実際のSheets API解析に接続する際は、対象ファイルとシートの許可リスト、文書種別、処理成功の記録を別途確認します。
- スナップショットには機密のファイルIDが含まれます。暗号文であっても、既定でGitHub・共有Drive・公開CIログへのアップロードは禁止します。
- 現状の保存APIは**単一の書込プロセスを想定**しており、複数プロセスの同時実行ロック・クラウド永続化・障害復旧は未実装です。これらが整うまでは本番の定期実行に使用しません。

## 差分からGoogle Sheetsの限定解析へ（開発用・読み取り専用）

`supplier_docs.change_processor.inspect_approved_sheet_changes` を追加しました。前回と今回のDrive差分に基づく候補のうち、**事前承認したGoogle Sheetsファイルとタブだけ**を、既存の `sheets_selected_tabs_summary` へ安全に引き渡します。

- 承認情報はプライベートな辞書 `approved_targets = {(folder_id, sheet_id): {tab_title: document_type}}` で呼び出し元が渡します。実ファイルID・タブ名・仕入価格は公開リポジトリやログへ保存しません。
- 差分にないファイル、変化していないファイル、Excel等の未対応形式、見知らぬタブ・不正な文書種別は拒否または保留します。
- API呼び出し前に、対象ファイル数は最大10、各ファイルのタブは最大10、合計読み取り上限は50,000セル、既定の対象は各タブ先頭40行・A:L列までと確認します。制限を超える要求は読み取り前に拒否します。
- 結果の `summary` は件数と注意コードだけです。ファイルIDを含む `private_inspections` と `pending_locations` は内部確認用の機密情報として扱います。
- **成功しても `baseline_advanced` は常に `False`** です。解析済みとして自動確定せず、価格・JAN・複数ASIN・規制などを手動または別途検証できる状態で残します。
- 途中のSheets APIエラーやタブ不一致では処理を失敗させ、部分的な結果を処理完了として扱いません。読み取り対象以外のDrive APIアクセス、スナップショット保存、Keepa分析、発注は実行しません。

この機能は **開発用のPython関数** です。自動実行ジョブには未接続で、Driveフォルダの追加共有や権限拡張もしていません。今回の確認は架空データによるテストのみで、複数ファイルに対する実運用の解析は未確認です。

## 変更資料のレビュー記録と再試行（開発用）

`supplier_docs.review_gate` と `supplier_docs.review_journal` を追加しました。変更・閲覧不可の資料に対する確認記録を**対象ファイルの更新版に結び付けて署名**し、暗号化したプライベートな作業記録として保持するための部品です。現状は人による承認画面やスケジューラには未接続です。

- `issue_review_receipt(...)`: *外部で本人確認と権限確認を済ませた専用レビュー処理のみ* が呼ぶ前提。承認者識別子・証拠参照・UTC日時・ファイルID・更新版ハッシュをHMAC-SHA256で署名します。**解析プログラムやスケジューラ自身が承認署名を生成してはいけません。**
- `plan_review_retries(...)`: 署名と承認者許可リスト、対象ファイルの更新版を検証。未確認・途中失敗分だけを再試行候補にし、変更がない資料を除外します。重複・改ざん・古い版・対象外の承認記録は黙って捨てずに停止します。
- `finalize_with_verified_receipts(...)`: すべての変更と閲覧不可項目に正しいレビュー記録が揃った場合だけ、次の基準点として使用可能な**Pythonのオブジェクトを返します**。自動的にディスクやDriveへ保存するものではありません。更新元の状態が途中で変わっていないかは運用側で再確認が必要です。
- `write_encrypted_review_journal(...)` / `read_encrypted_review_journal(...)`: 署名済みレビュー記録をFernetで暗号化し、所有者専用0700ディレクトリ内の0600ファイルへ原子的に保存。既存記録の削除・書き換えをAPI上は拒否し、続きのレビューだけを追加できます。上書き時は事前に読んだ暗号文リビジョンを要求します。
- レビュー記録とその署名・証拠参照・ファイルID・更新版ハッシュは**機密情報**です。GitHub・Colabの公開出力・共有ログには保存しません。日常のステータス確認は匿名件数の `summary` のみを使用します。

**重要な未実装範囲**：HMAC署名は、独立管理した署名鍵の保有を確認するものです。署名だけで本人確認や実際に人が資料を確認したことを証明できるわけではありません。承認画面の認証と権限管理、署名鍵と暗号化鍵の別々の安全な保管、書き込みロック・バックアップ・監査ログの耐改ざん保管は実運用前に必要です。現時点では架空データによる自動テストのみで、仕入れ承認・購入・本番ワークフローには接続していません。

## 秘密鍵をコマンドラインに渡さないWindowsの手動確認（未運用）

`local_backup_cli.py` は既存の暗号化済み監査アーカイブを手動で**検証**するか、明示承認後に**別の物理媒体と申告された保存先へ暗号文のみを新規コピー**する対話式入口です。復旧用Fernet鍵は `getpass` で非表示入力し、コマンドライン引数・環境変数・ログ・公開GitHubには渡しません。信頼済みEd25519公開鍵のJSONファイルは、**独立して確認したSHA-256指紋**に一致しなければ拒否します。端末入力や公開鍵ファイルの改ざん対策の完全な代替ではありません。

Windowsでは、ローカル保存先のACL・ディスク暗号化の確認を求め、非対話実行を拒否します。**実際のACL・BitLocker状態や物理媒体の独立性は検証しておらず、ユーザーのPCでの実使用も未実施**。バックアップ復元・鍵発行・自動送信・GitHub更新機能はありません。実際のコマンドと事前の安全確認は[`LOCAL_BACKUP_SAFE_CLI.md`](LOCAL_BACKUP_SAFE_CLI.md)を参照。WindowsとLinux双方の架空データ試験をPR CIに追加しました。

## Windows・Colabでの追加料金なしのバックアップ試験（未運用）

`local_backup_store.py` は暗号化済みの復旧アーカイブを**Windowsの信頼済みローカルフォルダまたはPOSIXの0700ディレクトリ**へ「新規作成のみ」で保存し、復旧鍵とEd25519公開鍵で署名履歴・破損を再検証する部品です。同名のバックアップへの上書きを拒否し、別の保存先へのコピーには「本当に別の物理デバイスである」と所有者が確認したという申告を必須にします。**保存先の物理的独立性を自動検証するものではありません。**

Windowsの**NTFS ACLやBitLockerの有効性は、このPythonコードから保証できません**。Windows側で権限・端末暗号化を手動で確認するまでは、実データの保存には使用しません。また、Google Colabの仮想マシンは永続保存先ではないため、開発検証用途に限定します。今回の機能はGitHubやGoogleへアクセスせず、実ユーザーのPCへの配置や秘密鍵の発行は行いません。

詳しくは [`LOCAL_BACKUP_WINDOWS_COLAB.md`](LOCAL_BACKUP_WINDOWS_COLAB.md) を参照してください。Windowsランナーの架空データ試験もPR CIへ追加しました。

## 非公開GitHubの復旧前チェック（未有効化）

`safe_restore_plan.py` は暗号化済みの復旧アーカイブを毎回検証し、**別途読み取ったGitHubの暗号文とblob SHAがアーカイブ元と一致しているか**を検査します。GitHub側の状態が取得できない場合、更新された場合、閲覧権限・承認者・バックアップと鍵の分離・原本の現在版の確認を証明できない場合は復旧を停止します。確認が揃っていても**ローカルの新暗号文を準備するだけ**でGitHubへの書き込みは行いません。操作担当者の申告フラグは実際の本人認証やDrive/GitHubの検証そのものではありません。

GitHub Freeで非公開リポジトリのブランチ保護・ルールセットを必ず使えるという前提を置きません。保護機能が利用できない場合や状態を検証できない場合は、自動的な機密データの保存先として採用せず、**追加費用のないローカル手動保管の代替案**を検討します。専用のStateブランチは実利用前の明示承認なしに作成しません。

GitHub Billingについては、現行の無料枠を**当月の共有ドル建てクレジット**で評価する設計ですが、実アカウントの使用額は読めていません。金額や残量が不明な状態で自動化しません。

## 復旧用の独立暗号鍵を使うオフラインバックアップ（新試験版）

`offline_recovery_archive.py` では、保存済みの暗号化監査履歴を別のFernet復旧用鍵で再暗号化したバックアップを作り、実保存前にEd25519署名履歴の整合性を検査します。復旧は手動承認が必須で、**GitHubの現在版やDriveの更新版を未照合のまま戻さない**設計です。モジュールはバイト列の作成だけで、バックアップ先への書き込み・本番操作・秘密鍵生成は行いません。復旧鍵とバックアップは別々の安全な場所に保管する必要があります。詳細は [`PRIVATE_AUDIT_BUNDLE_FREE_FIRST.md`](PRIVATE_AUDIT_BUNDLE_FREE_FIRST.md)。

## 更新履歴＋承認記録を1つにまとめる暗号化チェックポイント（推奨試験版）

`private_audit_bundle.py` と `private_github_audit_checkpoint.py` により、**更新履歴・過去のレビュー記録・Ed25519署名を一つの暗号化ファイル**として保存する候補を追加しました。古い履歴をすべて検証した後、GitHubの専用Private Repo／Stateブランチに対してblob SHAを指定した**単一ファイル更新**を要求します。未承認・旧版の承認・破損・競合を拒否し、暗号鍵や承認秘密鍵の自動生成・登録は行いません。

`actions_budget_guard.py` はGithub Billingの**当月の共有コンピュートクレジット使用額・ランナー単価が所有者によって確認されていなければ、月間無料枠が足りていると判定しない**費用ガードです。GitHub Freeで2026年11月に公式表示される含有額は**月12 USD**で、固定の2,000分ではありません。月30回×最大5分の最大150分を、確認済みのランナー単価でドルに換算します。実利用額は未取得。GitHub Freeの非公開リポジトリではEnvironment secretsの制限があるため、**有料プランを必要とする機能を前提にしません**。

この構成の詳細と未解決のセキュリティ課題は[`PRIVATE_AUDIT_BUNDLE_FREE_FIRST.md`](PRIVATE_AUDIT_BUNDLE_FREE_FIRST.md)を参照してください。**実GitHubへの保存、WIF認可、課金設定変更、スケジュール実行は未実施**です。

## 非公開GitHubへの更新履歴だけの暗号化チェックポイント（旧試験版・未実行）

`private_github_state.py` は、**承認された非公開GitHubリポジトリ内の専用ブランチ**へ更新履歴をFernet暗号化して保存・復元するアダプタです。ファイルのバージョンSHAを使い、競合時は上書きを中止します。初回は明示承認、2回目以降はEd25519署名による**全更新ファイルの確認記録**を要求します。実リポジトリ・実取引先への保存は未実行です。

**注意**：Git履歴には過去の暗号文が残り続けます。キーが漏れると過去の内容も復元され得ます。GitHub Actions の `GITHUB_TOKEN` の `contents:write` はファイルパス単位では制限できないため、**非公開リポジトリのコード保護・実行制限・鍵管理の検証が先決**です。ワークフロー実行時間の無料枠も未確認のため、追加費用ゼロの保証ではありません。

設計の詳細・留意事項：[`PRIVATE_GITHUB_STATE.md`](PRIVATE_GITHUB_STATE.md)。この方式の導入は所有者承認後に限定します。新規有料ストレージ・Cloud Run・Scheduler・Secret Managerを前提にしません。

## Windowsで所有者用の復号鍵を安全に扱う試験版（未導入）

`owner_key_vault.py` は利用者のWindows端末にX25519秘密鍵を**新規生成し、パスフレーズからScryptで導出したAES-256-GCM鍵による暗号化ファイル**に保管する開発用部品です。本人の秘密鍵の平文ファイルやGitHub Secretsへの登録は行いません。鍵ファイルとパスフレーズは**別々の場所にバックアップ**する必要があります。

`owner_result_cli.py` の `init-key`、`inspect`、`export` により、**対話端末から非表示入力**で初回鍵作成、GitHubから取得した暗号化データの件数確認、明示承認に基づくローカルJSON出力が可能です。ファイルを上書きせず、コマンド引数・標準出力へパスフレーズやメーカー価格を表示しません。**exportしたJSONは平文のため保護された非同期・非共有ローカルフォルダだけに保存**する必要があります。

WindowsのNTFS ACL／BitLocker／同期フォルダの有無は**プログラムだけでは証明できず、実Windows端末での確認も未実施**。実ユーザー鍵の発行、実GitHub Artifactの受信・復号、GoogleのWIF認証はまだ行っていません。詳しい手順と注意は[`OWNER_WINDOWS_DECRYPT.md`](OWNER_WINDOWS_DECRYPT.md)を参照。新機能は公開開発PRで架空のデータ・鍵のみでテストします。

## メーカー詳細情報の利用者宛て暗号化（開発用・未配信）

前回の「GitHubログには匿名件数だけ」という制限を維持したまま、`private_result_envelope.py` により**詳細なメーカー資料の解析結果を利用者のX25519公開鍵でAES-256-GCM暗号化**する機能を追加しました。暗号化時に毎回一時X25519鍵とnonceを作り、独立して確認した受信者公開鍵のSHA-256指紋が一致しないと拒否。**復号用の利用者秘密鍵はGitHubやGoogleに渡しません**。

`private_result_file.py` はGitHub Runnerの専用一時フォルダに**暗号文だけを新規作成**し、既存ファイルの上書きを拒否します。`manual_sheet_probe.py` は暗号化モードが指定されたとき、**Google APIを呼ぶ前に受信者鍵設定を検証**し、詳細な卸価格や商品データを暗号化ファイルに入れます。GitHub Actionsログには匿名件数しか出さず、失敗時もGoogle API原文を表示しません。

未設置の[`templates/supplier-readonly.yml`](templates/supplier-readonly.yml)には、暗号化ファイル**だけ**を短期保存（1日）する `actions/upload-artifact@v4` の設定例を追加しました。**実Private Repo・実WIF・実メーカー資料への接続やArtifactアップロードは未実施**。GitHub Actions保存容量やRunner計算費の課金確認も未完了です。

**これは機密の転送を可能にする部品で、最終的なユーザー参照画面ではありません。** 利用者自身の秘密鍵の安全な発行・保管・ローカル復号手順と、ChatGPTが必要なデータを安全に参照する権限付きチャネルはまだ未完成。詳しくは[`OWNER_ENCRYPTED_RESULT_DELIVERY.md`](OWNER_ENCRYPTED_RESULT_DELIVERY.md)を参照してください。

## GitHubから必要時にGoogle Sheetsを読み取る入口（開発版・未接続）

`on_demand_reader.py` は**私的な許可リストをもとに最大3 Google Sheets／合計7,200セル**の明示指定タブだけを読み取り、メーカー資料・商品・JAN・ASIN・卸値などの解析結果を**プログラム内部の機密戻り値**へ保持します。公開してよいのは別に返される匿名の件数サマリーだけです。Drive全体のフォルダ検索・原本の編集・更新状態の自動確定・自動発注はありません。

`manual_sheet_probe.py` は**承認済みのPrivate GitHub Actionsで手動起動する想定**の実行入口。非公開リポジトリ／mainブランチ／特定workflow／`workflow_dispatch`／Google WIF資格情報の条件がそろわなければ拒否します。API失敗時の例外・取引先データをGitHubログに表示しません。Google側WIF providerにも不変のリポジトリID・所有者ID・workflow等の条件が必要で、**実WIF認可やPrivate Repoへの配置はまだ行っていません**。

プライベート専用リポジトリへの**未設置テンプレート**は `templates/supplier-readonly.yml`。詳細と残る課題は[`ON_DEMAND_PRIVATE_GITHUB.md`](ON_DEMAND_PRIVATE_GITHUB.md)を参照してください。現時点のActionsログは匿名件数のみで、**詳細なメーカー資料をユーザーやChatGPTがGitHub経由で取得できる配信先は未実装**です。

## 追加月額費用を避ける設計（最優先、未デプロイ）

取引先資料の自動化は**新たな固定費や課金可能なクラウドリソースを既定にしない**方針です。以下の既存の無料・契約内の選択肢を先に評価します。

- **既存GitHub Actions**：検査や解析は標準Runnerを再利用。公開Repoではコード・架空データのCIのみとし、機密の仕入価格・取引先名・認証情報・ファイルIDを公開ログ・リポジトリ・Artifactへ保存しない。Private Repoの無料実行枠は所有者アカウント全体の利用と課金設定の確認が必要。
- **Google Apps Script**：Driveの少数の承認済みフォルダの更新検出・通知だけを限定実行する案。別途クラウドJobを作らずに済む可能性はあるが、ユーザー承認、Driveへの広い権限のリスク、実行時間やProperties容量などの制限を先に検証する。
- **既存の非公開保存先**：前回からの差分や秘密の更新履歴は、別途権限を確認したPrivate Drive等への保存を検討。公開コードに暗号化済みの原本IDを無造作に置いたり、CIの一時Artifactへ長期保存したりしない。
- **オフライン公開鍵レビュー**：`offline_review.py` は信頼済みのレビュー端末だけがEd25519の秘密鍵で署名し、解析ワーカーは公開鍵だけで署名の真偽と対象の更新版を確認する**試験実装**。これにより、レビュー署名用の課金サービスやSecret Managerの新規Secretを必須にしない選択肢が生まれる。本人認証・鍵管理・証跡保存・承認UIは未整備。
- **費用ガード**：`cost_first.evaluate_cost_first_plan` は課金リスクが残る新規サービスを所有者の明示承認なしで禁止し、無料枠や機密保存先が未確認なら設計のみで停止する。これは金額や課金状態を実際に検証するプログラムではない。

先に提案したCloud Run Job、Cloud Scheduler、2つのGCSバケット、3つのSecret Manager Secretは**候補のまま保留**します。無料試用クレジットには依存せず、ランニングコスト・手間・セキュリティ・実行安定性を比較して必要な場合だけ採用します。既存のAmazon SP-API自動化環境には手を加えません。

公式資料：
- [GitHub Actions利用料金](https://docs.github.com/en/billing/concepts/product-billing/github-actions)
- [GitHubプランと無料枠](https://github.com/pricing)
- [GitHub Actions scheduleの制約](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows)
- [Google Apps Scriptの割り当て](https://developers.google.com/apps-script/guides/services/quotas)
- [Cloud Storage Always Freeの対象リージョン](https://cloud.google.com/storage/pricing)

## 将来のGoogle Cloud実行構成（未デプロイ）

Cloud Run **Job** + Cloud Scheduler + Secret Manager + 非公開Cloud Storageの構成を候補とします。現時点では**設計と開発用アダプタのみ**で、Google CloudにJob・バケット・Secret・Schedulerを作成したわけではありません。既存のSP-API用Cloud Run Job、サービスアカウント、スケジューラ、GCSを変更する手順は含みません。

- `supplier-docs-worker`（将来のJob実行用SA）: 原本の読み取りと差分候補作成のみ。専用の `supplier-docs-reader` サービスアカウント**単体**へのToken Creatorを付与して代理認証し、Drive metadata readonlyとSheets readonlyの**それぞれ別の短命トークン**を利用する想定。対象フォルダへのViewer共有が別途必要です。**既存SP-API用SAは利用しません**。
- `supplier-docs-review`（将来の認証済みレビューサービス用SA）: 人による実確認・承認記録の発行を担当。HMAC署名用Secretはこのサービスのみが閲覧します。レビューの本人認証・監査ログは未実装。
- `supplier-docs-trigger`（将来のScheduler用SA）: 指定したSupplier Jobを起動する権限だけを持つ。Google APIのジョブ実行URLにはOAuthトークンを使います。**現時点ではスケジューラを作成・有効化しません**。
- **2つの独立したPrivate GCSバケット**：`supplier-docs-state-...` は暗号化した `supplier-docs/inventory.enc` のみ、`supplier-docs-review-...` は暗号化した `supplier-docs/review-journal.enc` のみを保持。Workerは前者を読み書き、Reviewerは前者を閲覧するだけで後者を読み書き。Workerにはレビュー署名鍵やレビュー記録へのアクセスを与えません。既存SP-APIバケットは不使用。更新はGCS世代番号の一致を要求します。公開アクセス防止、バージョニング、最小権限IAM、バックアップ・復元計画は導入前に要確認。
- Secret Managerの**3つの別々のSecret**: インベントリ暗号鍵（Workerのみ）、レビュー記録暗号鍵（Reviewerのみ）、署名鍵（Reviewerのみ）。アクセス権は**各Secret単体**に付与し、バージョンを明示します。実鍵はコード、GitHub Actions、Colab、標準ログに保存しません。

### 開発中の安全制御

- `supplier_docs.cloud_runtime.validate_supplier_cloud_runtime` は非公開の配置案を**ネットワークアクセスなし**で検査します。Job・SA・分離した2バケットがSupplier専用であること、役割分離、Secret3個の分離と版固定、`dry_run`、スケジュール無効、単一並列、リトライ0、原本ログ無効、レビュー自動承認無効、Drive再帰探索無効を要求します。結果は匿名のチェック項目だけです。
- `supplier_docs.auth.build_readonly_drive_metadata_service` は既存のSheets認証とは分離した `drive.metadata.readonly` の15分代理トークンを使います。Drive API有効化や実フォルダ共有は**まだ実施していません**。
- `supplier_docs.cloud_state` は呼び出し元が明示的に渡した専用GCS Blobのみに暗号化した状態をアップロード・ダウンロードします。GCS世代前提条件で他の実行による上書き競合を防ぎ、未許可のバケット名・オブジェクト名は拒否します。**実GCSへの接続テストは未実施**。
- インベントリとレビュー記録は**別々のGCSバケット／オブジェクト**のため、両方をまとめて更新するトランザクションではありません。導入前に単一実行保証、障害時の復旧、鍵ローテーション、暗号文のバックアップ、レビュー監査証跡を設計・検証します。

### 導入前の最小権限・費用プレビュー（オフライン）

- `supplier_docs.deployment_review.plan_supplier_iam` は承認候補のIAMバインディングを**機密な内部リスト**として生成し、匿名のチェック結果を返します。Worker→Reader SAの `roles/iam.serviceAccountTokenCreator` はReader SA**単体**へ。Workerの `roles/storage.objectUser` はインベントリバケット単体、`roles/secretmanager.secretAccessor` はインベントリ鍵Secret単体。Reviewerのインベントリバケットは `roles/storage.objectViewer`、レビュー用バケットは `roles/storage.objectUser`、ジャーナル鍵と署名鍵は各Secret単体です。Schedulerの `roles/run.invoker` はSupplier Job単体への**将来の提案のみ**で、現時点では付与しません。
- `validate_exact_iam_proposal` は付与候補リストへの管理者権限追加・スコープ拡大・欠落を拒否します。**実際のIAMを読み取って検査する機能ではなく、IAM変更も行いません**。レビュー署名の安全な受け渡しと2バケットの整合性保証は未解決なので、この段階で本番デプロイを許可しません。
- `supplier_docs.budget_review.estimate_pilot_usage` は想定負荷を厳しく限定した**概算の使用量計算**で、費用見積書ではありません。例として1 vCPU・0.5GiB・1回120秒・月30回ならCPU 3,600 vCPU秒／メモリ1,800 GiB秒です。Cloud Runの公表参照無料枠240,000 vCPU秒／450,000 GiB秒と比べるだけで、東京リージョンの請求額、請求アカウント全体の既存利用量、ストレージ・レジストリ・ログ・API・通信費用は確定しません。
- Cloud Schedulerは**無効・0ジョブ**が初期設定です。将来1ジョブにする場合は、請求アカウント共通の3ジョブ無料枠を使い切っていれば約$0.10／31日（2026年11月時点の公表単価）。Secret Managerの無料枠も請求アカウント共通で、アクティブなSecretバージョン最大6個と月10,000回のアクセスが無料枠です（既存利用分は未確認）。Artifact Registryは請求アカウント単位で0.5GiB月の無料枠があります。Cloud Storage・ログ保持・転送量・監視費用も別途確認が必要です。
- 原本の価格・取引先名・ファイルID、IAMの実メールアドレスやバケット名を**公開リポジトリへ含めない**。料金をゼロ円と断定せず、Google Cloud Billingの実使用量・予算アラート・公式料金計算機による確認後に進めます。

### Google公式資料（将来の導入時に再確認）

- [Cloud Run JobのサービスID](https://docs.cloud.google.com/run/docs/configuring/jobs/service-identity)
- [Cloud Run JobのSecret管理](https://docs.cloud.google.com/run/docs/configuring/jobs/secrets)
- [Secret ManagerのSecret単位IAM](https://docs.cloud.google.com/secret-manager/docs/access-control)
- [Cloud Storageの世代前提条件](https://docs.cloud.google.com/storage/docs/request-preconditions)
- [Cloud Run JobをSchedulerで実行](https://docs.cloud.google.com/run/docs/execute/jobs-on-schedule)
- [Cloud Runの料金と無料枠](https://cloud.google.com/run/pricing)
- [Cloud Schedulerの料金と無料枠](https://cloud.google.com/scheduler/pricing)
- [Secret Managerの料金と無料枠](https://cloud.google.com/secret-manager/pricing)
- [Artifact Registryの料金](https://cloud.google.com/artifact-registry/pricing)
- [Cloud Storageの料金](https://cloud.google.com/storage/pricing)
- [Cloud Runの実行IAMロール](https://docs.cloud.google.com/iam/docs/roles-permissions/run)
- [Cloud Storageの権限スコープ](https://docs.cloud.google.com/storage/docs/access-control/iam-roles)

## Cloud Run Jobの障害復旧シミュレーション（開発用、完全オフライン）

`supplier_docs.recovery.assess_recovery` は、スキャン開始時の基準点・更新候補・実際の保存済み状態・GCS世代番号・署名付きレビュー記録を照合する**純粋な判定関数**です。外部APIの呼び出し、スナップショット書き込み、署名発行や承認を行いません。

- 保存済み状態が元の基準点のままで、未確認資料が残る場合は `resume_only_unreviewed_items` を返し、署名済みの確認済み資料は再確認候補から除きます。
- 全件確認済みでも `ready_for_external_revalidation_not_committed` と返します。**別の信頼済み処理で原本の更新版を再確認し、GCSの世代番号で条件付き保存するまで完了扱いにしません**。
- GCSの世代番号が開始時と違う場合は `halt_concurrent_inventory_generation`、保存済みの内容が予期せず変わった場合は `halt_unexpected_persisted_inventory` として停止します。
- **スナップショット保存は成功したが、その直後にジョブが停止した場合**は `halt_advanced_inventory_requires_journal_reconciliation` とし、人によるレビュー記録と保存状態の照合を要求します。現状、インベントリとレビュー記録は別々のGCSオブジェクトであり、双方をまとめて確定するトランザクションは未実装です。
- **ソース資料が変更された場合は以前の承認を流用しません**。古い版の署名、改ざん、未許可承認者は例外とし、復旧結果を確定しません。

### 認証情報が不要なドライラン

```bash
cd manufacturer_checker
python -m supplier_docs.job_dry_run --scenario after_scan
python -m supplier_docs.job_dry_run --scenario partial_review
python -m supplier_docs.job_dry_run --scenario all_reviewed
python -m supplier_docs.job_dry_run --scenario cas_committed
python -m supplier_docs.job_dry_run --scenario cas_conflict
python -m supplier_docs.job_dry_run --scenario unchanged
```

この入口は**架空データ専用**です。Google Cloudの認証情報や本番データを読み込まず、外部通信もしません。出力は匿名の件数と復旧方針のみです。`--live`、自動承認、スケジュール実行などの引数は受け付けません。GitHub ActionsのPR用CIでもクラッシュ・競合の代表パターンを実行します。

**残る本番導入要件**：Cloud Run用のコンテナ化、Cloud Run Jobの実行環境、専用IAM・Secret・Cloud Storage、書き込みロック／クラッシュ復旧と2オブジェクト間の整合性保証、実フォルダの追加閲覧権限、本人確認を伴う承認画面、実データでの統合テスト。これらはまだ設定・実行していません。既存のSP-API本番リソースは変更していません。

## ドライラン専用コンテナ（開発用、非デプロイ）

`manufacturer_checker/Dockerfile.supplier-docs-dry-run` は **架空データの障害復旧シミュレーション専用**です。`Dockerfile.supplier-docs-dry-run.dockerignore` でビルド対象を最小化し、`supplier_docs` のうちテストに必要な7ファイルだけを同梱します。Google Cloud認証・Drive API・Keepa・SP-API関連モジュール、取引先資料、実ファイルIDは同梱しません。

実行時はLinuxの非rootユーザー（UID 10001）で `python -m supplier_docs.job_dry_run` を起動します。`--live` や自動承認用の引数は存在しません。Cloud Run Jobへのデプロイ、実GCPへのアクセス、Schedulerの有効化、Secretやバケットの作成は一切行っていません。

開発環境にDockerがある場合の**ネットワーク遮断・読み取り専用**試験例：

```bash
docker build -f manufacturer_checker/Dockerfile.supplier-docs-dry-run -t supplier-docs-dry-run:local manufacturer_checker
docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges supplier-docs-dry-run:local --scenario after_scan
```

Draft PR用GitHub Actionsは別ジョブでコンテナを**ビルドするだけ**で、レジストリにpushしません。ネットワークを遮断した実行コンテナで6種類の障害ケースを検証し、機密IDが出力されないこと、UID 10001・除外された認証モジュール・危険なCLIオプションを確認します。

**限界**：これは本番用のGoogle Cloudワーカーではなく、復旧ロジックの安全な実行単位を先に確立するものです。実導入には、別途安全なワーカーイメージ・最小権限IAM・Google Cloudのリソース作成、クラッシュ時の状態整合性・バックアップ・レビュー本人認証を検証する必要があります。OSイメージと依存パッケージの固定・脆弱性検査も本番前の必須作業です。

## 安全なAPI接続の試運転

上の鍵なし代理認証手順に従い、まず1シートの40行以内だけを `--summary-only` で試験してください。サービスアカウントはViewer権限のみ、トークンは15分の `spreadsheets.readonly` スコープです。

- `--sheet-range` は有限のA1範囲（最大50,000セル）しか受け付けません。
- `--summary-only` の表示はレコード数と警告・リスクコードの件数のみです。ファイルID・商品名・JAN・ASIN・卸値・取引条件の原文を表示しません。
- ソースコードにはSecret、実Google Sheets ID、取引価格・顧客情報を保存しません。
- 実認証・権限付与は各Googleアカウント側の所有者操作が必要です。このPRのCIは合成データのテストのみです。
- Google Sheets APIの読み取りだけを許可していますが、Colabなどでログインする**元のアカウントの権限自体を縮小するものではありません**。APIへ渡す専用アカウントを最小化する設計です。

## 出力と保護

既定の標準出力は**原価と備考を伏せた**JSONです。元ファイルへの更新はしません。

卸値などの詳細が必要な場合のみ、アクセス制限されたローカル保存先を指定します。

    python -m supplier_docs.cli --input /path/to/quote.xlsx --document-type quote_response --include-sensitive --output /private/path/result.json

保存先は新規ファイルのみ（既存ファイルは上書きしない）、Unix系では所有者のみのアクセス許可を指定します。OSの設定や保存先共有権限も別途確認してください。**実見積、原価、取引先の個人情報、出力したJSONをGitHubへコミットしないでください**。ファイルのパスや原本のURLにも取引情報が含まれる場合があります。

出力には source_file_id / source_sheet / source_row、JAN（文字列）、ASIN候補（照合未確定）、発注単位、税区分、既存利益判定の状態、リスクコードを含みます。すべての行の decision は needs_confirmation で、仕入れの自動承認はしません。

## 注意点

- JANがExcel側で数値として保存されていた場合、失われた先頭ゼロは復元できません。警告します。
- ASINが無題列にある場合は、B0で始まる10桁だけを**候補**として扱い、確認を要求します。
- 見積依頼・見積回答シートでは、見出しが空欄のASIN列や利益判定列を**5行以上の高一致率かつ80%以上の行網羅率**で推定できます。推定した列は `inferred_columns` と `summary.inferred_fields` に明示し、各行へ `ASIN_UNLABELED_COLUMN_INFERRED` / `PROFIT_UNLABELED_COLUMN_INFERRED` の警告を残します。候補列が複数ある場合や根拠が不足する場合は推定しません。原本の確定的な見出しとしては扱いません。利益ラベルはあくまで**原本の既存判定**であり、利益再計算や仕入承認ではありません。
- **複数ASIN**が1セルにある場合、`asin_candidates`に全候補を残し、`asin_candidate`（単一候補欄）は空にします。単品／セットを選びません。
- **卸側の商品名が空欄でAmazon名／ASINのみ**の行も失わず記録し、`SUPPLIER_PRODUCT_UNKNOWN`を付けます。
- **メーカー別シート**は`source_group`にシート名を保持しますが、シート名を契約先・製造元の確定情報に読み替えません。
- **取引条件がグループ先頭行にしかない**場合、明確な連続行の範囲で注意情報を継承し、メーカー切替や空行でリセットします。金額・原文は既定の出力へ含めません。
- 先頭ゼロの前に不可視文字が付いたJANは、除去したうえで警告します。元のコードが正しい保証はありません。
- 見出しの同義列が重複した場合は片方を推測で選ばず、その項目の抽出を保留します。
- 黒字（競合によっては赤字）等は条件付きと判断し、単純に黒字として採用しません。
- EC不可・取り扱い不可・直送限定・定価販売等はリスクコードとして記録します。規制や契約上の実効性を判断する機能ではありません。
- Google Sheetsの表示形式で失われたJANの0や数式の計算結果の検証は保証しません。
- PDF、結合セルの特殊な配置、複数の独立した表を持つシート、Excelの外部リンク等は未対応です。原本を読んで手動確認してください。

## テスト

    cd manufacturer_checker
    python -m unittest discover -s tests -p 'test_supplier_*.py' -v

異なる列順・複数ASIN・ケース条件を架空データで検証しています。テストはすべて架空データです。実際の取引先・仕入価格・Drive IDはコードに含めません。

業務上の項目定義は非公開の amazon-business-knowledge/suppliers/field-schema.md を参照してください。公開リポジトリから直接参照・取得できるとは限りません。

**実Google Sheetsとの照合（2026-11-08）**：`FORMATTED_VALUE` の返却値は数値JANも文字列として返すため、数値セルから先頭0が失われているか判定できません。`FORMULA` に変更して生の数値型を保持し、式は文字列として処理・不採用とします。実資料の金額・原文をGitHubに保存しないでください。その後、専用サービスアカウントによるGoogle Colabからの実接続と先頭40行の読み取り・集計（39件）は成功しました。その後、列推定機能の更新後も井上のColab再テスト成功、ワコーフーズについても専用SAで29件を解析し、重複する卸値列・複数ASIN候補を正しく保留しました。**手動の接続テストは2社分完了**しました。Driveのメタデータ差分検出は合成データのみで検証済みです。
