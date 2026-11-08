# 無料枠優先：Private GitHub Actions + Google専用Reader（設計・未有効化）

**状態：オフライン検査のみ。** GitHubのworkflow、Google Cloud IAM、WIFプロバイダー、サービスアカウント共有範囲、請求設定はまだ変更していません。既存SP-API本番環境を転用しません。

## 採用を検討する理由

Apps Scriptの `drive.metadata.readonly` は実行ユーザーのDriveメタデータへ広く及ぶ可能性があります。一方、専用Readerサービスアカウントに**明示共有した資料だけ**を閲覧させる方式なら、原本へのアクセス範囲をより狭く管理できます。GitHub Actionsの標準runnerは含有クレジットを使える可能性がありますが、**GitHub Freeの月12 USD共有コンピュートクレジット**に、Private Repoなどの対象利用の計算額が加算されます。固定の月2,000分を残量として扱わないでください。実際に追加費用がないかは未確定です。

## 最低限の構成

1. **非公開の専用GitHubリポジトリ**を使用。既存の公開 `manufacturer-keepa-analysis` はコードと架空データのテストだけに限定。仕入価格、契約、実ファイルID、Google Cloud認証ファイル、レビュー署名の秘密鍵を公開リポジトリやログに載せない。Private RepoでもArtifact・ワークフローログ・第三者のActionsに機密を渡さない。
2. **GitHub Actionsを手動起動限定**（`workflow_dispatch`、保護された `main` の特定workflowのみ）。PR・fork・scheduleから外部Google認証を使わせない。workflow/jobの権限は必要なJobだけ `contents: read` / `id-token: write`、他は最小化。
3. **OIDC / Google Workload Identity Federation (WIF)** を用い、秘密鍵JSONの長期保管を避ける。Google側のOIDC providerの `attributeCondition` では**不変のGitHub owner_id・repository_id、branch ref、event_name、workflow_ref**を照合。条件はGitHub workflow中の `if:` ではなく、**Google側providerにも設定すること**。既存のSP-API OIDCプロバイダーを、そのまま取引先資料へ流用しない。
4. 対象Google APIに必要なアクセスは**Reader SAだけ**へ。WIFの `roles/iam.workloadIdentityUser` が必要な場合、対象Reader SA**単体**に付与し、プロジェクト全体や旧SP-API用SAに付与しない。**Google側IAM設定はまだ未実施**。
5. 同一Google Sheetsでも読むシートと範囲は明示設定。既存の `spreadsheets.readonly` を使用し、価格などの原文をGitHubログに出さない。Driveフォルダ巡回権限やファイル共有を勝手に増やさない。
6. GitHub Runnerは実行ごとに一時的な環境になるため、**差分の前回スナップショットを永続化する非公開の保存先**が別途必要。専用Readerの閲覧権限と保存用の書込権限は分ける。保存先の安全性・所有者アクセス・費用が未解決なら**初回の実行を有効にしない**。
7. 無料枠に収まるかGitHub Billingの当月共有コンピュートクレジット使用額とGoogle Sheets/Drive APIの現在のクォータを確認。Google Sheets APIは標準使用が無料と案内されているものの、**2026年後半にクォータ超過への課金が予定されている**ため、API呼び出し上限を明示し、超過時に再試行連打をしない。既存Keepaの追加APIコール費用も増やさない。

## 開発用事前検査

`supplier_docs.github_wif_review.plan_private_github_wif` は、実在しないダミーIDで安全条件とGoogle側へ設定すべきCEL条件の構文を確認する**純粋なPython関数**です。実GitHubリポジトリID・Googleプロジェクト番号・サービスアカウントのメールアドレスを公開CIログに出さないこと。返り値の `private_required_provider_condition` は**非公開のレビュー資料だけ**で扱います。

この関数はGoogleの設定やGitHub Billing残高を実際に確認できません。すべてのローカル確認項目に値を入れても `eligible_for_separate_manual_test_review` となるだけで、実行開始・デプロイ・認可ではありません。

- テスト：`python -m unittest discover -s manufacturer_checker/tests -p 'test_supplier_github_wif_review.py' -v`
- **公開GitHubでOIDCトークンを発行するworkflowは追加していません**。
- 請求、Drive権限、非公開state、レビュー認証が未解決のため**採用可否は保留**。必要なら所有者へ候補別の費用・影響を示してから設定する。

## Apps Script案との比較

| 判断材料 | Apps Script（試験版） | Private GitHub Actions＋Reader SA（試験設計） |
|---|---|---|
| 追加月額費用 | Apps Scriptの割り当て内なら可能性あり | GitHub無料分・Google APIクォータ内なら可能性あり |
| 原本の閲覧者 | ログインしたGoogleユーザー | 限定Viewer共有された専用Reader SA |
| 監視範囲 | コードは20ファイル上限だがOAuthは広い | 専用SAに共有したファイルへ限定可能 |
| 実行 | 手動Previewのみ実装済み | Offline設定検査のみ実装、**実認証なし** |
| 機密な状態保存 | Script Propertiesは編集者が見られる | Private保存先を別途設計する必要 |
| 主なリスク | 広いGoogleユーザーOAuth権限 | GitHub課金・WIF設定ミス・Private Repoの秘密管理 |
| 結論 | 導入保留 | **プライバシー面で優先検討**、導入保留 |

## 公式資料（2026-11-08に再確認）

- [GitHub Actionsのドル建て共有コンピュート料金](https://docs.github.com/en/billing/concepts/product-billing/github-actions)
- [GitHub OIDCの権限](https://docs.github.com/en/actions/reference/security/oidc)
- [Google CloudのWIF／GitHubの条件](https://docs.cloud.google.com/iam/docs/workload-identity-federation-with-deployment-pipelines)
- [Google Cloud WIF](https://docs.cloud.google.com/iam/docs/workload-identity-federation)
- [Google Sheets APIの割り当てと料金](https://developers.google.com/workspace/sheets/api/limits)

**これまで通り、新規の有料サービスは勝手に追加しない。** 実際の認可、GitHub Actionsに秘密を渡す操作、スケジュール有効化を行う前に、対象リポジトリ・権限・費用・保存先を個別にレビューする。
