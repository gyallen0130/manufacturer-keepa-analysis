# 初回実接続は「1ファイルのGoogle Drive版番号だけ」：オーナー向け試験計画

2026-11-09 JST / **未接続・未有効化** / public開発ブランチ内のテンプレートとテストのみ

## 背景

これまでの`templates/supplier-readonly.yml`は、Google Sheetsの商品行を読み、所有者暗号化アーティファクトをアップロードする**将来用の機能全部入り案**。Google CloudのWIF/IAM、GitHubのプライベートリポジトリ制御、従量課金の安全条件が未検証の現在、最初のWIFテストに使用するべきではない。

**今回追加**した`templates/version-only/supplier-readonly.yml`は、**最初の認証試験用**の狭いテンプレート。

- 既存の**別のPrivate知識リポジトリ**へ、完全なコード審査とオーナー承認の後だけ`.github/workflows/supplier-readonly.yml`として1ファイル配置することを想定。現時点でPrivate repoのワークフローを**一切設置していない**。
- GitHub Actionsは`workflow_dispatch`の手動起動のみ。private repo・`main`・manual eventの条件でジョブを制約。タイムアウト3分、単一並列グループ。
- ジョブは`contents:read`、`id-token:write`以外の権限なし。チェックアウト時にGitHub認証情報を保持しない。
- 固定コミットの`actions/checkout`、`actions/setup-python`、`google-github-actions/auth`の3つのみ。2026-11-09に**各コミットが該当公開リポジトリに存在**することは確認したが、**ソース監査と署名の独立検証が完了したわけではない**。
- Linux/Python 3.11の承認済みSHA256ホイール指定（`--require-hashes --only-binary=:all:`）、依存再現性のみ担保。新しいPyPIパッケージを無審査で足さない。
- 既に用意した`manual_drive_version_probe.py`を使い、**Google Drive v3 files.getの`id,mimeType,version`だけ**を取得する。商品行・数式・JAN/ASIN・原価を読まない。1件の指定原本ファイルへの認証付きメタデータ照会だけ。
- 成功なら`status=raw_drive_v3_monotonic_version_available`等の**匿名JSON**、失敗なら匿名の停止JSON。ファイルIDと版番号そのものは印字しない。
- 成果物`upload-artifact`、定期スケジュール、Google Driveファイル書込み、情報を受け取る外部Webhook、アプリキーの保存を行わない。

**重要**：このテンプレートの配置やmanual実行は**Google Cloud IAM認証・請求停止条件・GitHubコードのレビューが完了した上で**所有者に別途承認されるまで行わない。

## 残る判定チェック：上から順に実施する

1. **Cloudの実IAMが未確認**：まずCloud Shellの[WIFブートストラップ読取コマンド](WIF_BOOTSTRAP_READONLY.md)でProvider/Readerの基本状態を非機密で確認。次に[SHA固定まで含む厳密監査](PINNED_WIF_CONNECTION_REVIEW.md)で、本人のimmutable Github repo/owner ID、`assertion.workflow_ref`、`assertion.workflow_sha`、`assertion.sha`、`private`、`workflow_dispatch`、GitHub-hosted runner等がGoogle Cloud側の実設定と**完全一致**し、専用Reader以外へアクセスを広げないことを独立検証する。
2. **GitHubの課金停止条件が未確認**：所有者本人が[GitHub Settings > Billing > Budgets and alerts](https://github.com/settings/billing)で、Private repoのActions計算分およびArtifactsなどの利用状況、適用予算の範囲、停止設定を確認する。**単なるメール通知設定を課金停止と取り違えない**。GitHub公式：https://docs.github.com/en/billing/how-tos/set-up-budgets
3. **Private repoの`main`は未保護**：現在利用中プランではPrivate branch rulesetsが使えないため、Google Cloud側でworklow/sourceの実コミット両SHAを**レビューした一致値に固定**する。ただしこれはGitHubの保護ブランチと等価ではない。workflowの配置やコードの差し替えは**新たなIAM固定値の再審査が必要**になるため、仮のbranch HEADを固定値に使わない。
4. **Private repoに検査用コードが未配置**：インストールする場合は、開発Repoのレビュー済み特定commitから必要なPythonモジュールと`approved-requirements-hashed.txt`を**本人が検証してPrivate Repoへ取り込む**。GitHub Actionsの実行時に`main`から変更可能な開発ブランチを`curl | bash`で取得しない。
5. **Private repoの変数/Secretは未設定**：検査用に`vars.SUPPLIER_WIF_PROVIDER`、`vars.SUPPLIER_READER_SA`、`secrets.SUPPLIER_APPROVED_SHEET_ID`を使用する設計。実値は承認済みの最小権限の原本**1件**に限定し、チャット・公開GitHub・Actionログ・ローカル平文ドキュメントへコピペしない。
6. **独立したセキュリティレビューと所有者承認**：3つの固定Actionコミットの差分と依存供給元、Private Repo実権限、Google ReaderのDrive共有範囲、WIF Condition、費用・ログの保持期間を確認してから、**1回だけの手動実行**可否を別途決める。

## 後続の検索との関係

- この試験が実際に成功したら、Google原本の`version`を使う200行超の継続検索を**同じ認証主体で**検証できる可能性が生まれる。
- ただし、このworkflow自体は**Driveメタデータだけ**。原本Google Sheets内容をPrivate Pythonへ渡すread-only Sheetsアダプター、本人認証付きChatGPT UI、112社索引・ページングの恒常運用は**別工程で未完成**。
- 過去に成功した777件のテストや新しいテンプレートの静的検査は、**実WIF権限、実版番号、実費用の保証にはならない**。

## 採用するセキュリティ根拠

- GitHub公式: https://docs.github.com/en/actions/reference/security/secure-use （外部Actionを完全コミットSHAで固定し、内容を審査する）
- Google Cloud公式: https://docs.cloud.google.com/iam/docs/best-practices-for-using-workload-identity-federation （複数テナントGitHub OIDCにはテナント・repoの信頼制約が必要）
- GitHub公式: https://docs.github.com/en/billing/how-tos/set-up-budgets （通知と利用停止は別条件）
