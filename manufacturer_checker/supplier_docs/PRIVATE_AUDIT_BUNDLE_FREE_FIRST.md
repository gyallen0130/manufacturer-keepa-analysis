# 追加月額費用なしを目指す：Private GitHub暗号化監査チェックポイント

**状態：開発用の設計・架空データテストのみ。非公開Repoへ実データ未保存、GitHub SecretsやActions認証設定の変更なし。**

## 旧版との差分

- **旧 `private_github_state.py`**：暗号化した更新履歴だけをPrivate GitHubの専用ブランチに置く試験版。承認記録の保存は別工程だった。
- **新 `private_audit_bundle.py` ＋ `private_github_audit_checkpoint.py`**：`initial_snapshot`、`current_snapshot`、改ざん検出可能な更新版ハッシュ、**すべてのEd25519署名済みレビュー記録**を**1つの暗号化JSONにまとめる**。更新ごとに過去の署名をすべて再検証し、GitHub Contents APIの既存blob SHAに一致した場合だけ1つの暗号文ファイルを更新する。
- 新版の保存先は**Private Repo内の** `supplier-monitor-state` ブランチの `private-state/supplier-docs-audit-v1.enc` のみ。旧版の `private-state/supplier-docs-inventory.enc` と明示的に分離している。旧ファイルからの無断移行・初期化・上書きはしない。
- **利点**：更新履歴とレビュー記録を別ファイルに保存すると片方だけ更新される障害があり得た。1つにまとめることでこの不整合リスクを減らす。ただし、原本のDrive更新がGitHub保存直前に進んだかどうかは呼出側で再検証が必要。GitHub側の書込成功が不明なネットワーク障害は自動成功と判定しない。
- 監査の最大履歴は**64サイクル**、1サイクルは最大**1,000件の署名済み記録**、JSON平文は最大約**4.5MB**。上限に達した際は自動削除・自動圧縮しない。明示的な保管／移行案を作ってから進める。

## 秘密鍵・暗号鍵の扱い

- **承認用Ed25519秘密鍵は確認担当の安全な手元にのみ保持**。GitHub Secrets、Actions、公開GitHub、分析ワーカーには一切渡さない。解析側は信頼された公開鍵だけで承認記録を検証する。署名を作る前に実際の確認・本人認証を行う仕組みはまだ未実装。
- **チェックポイントのFernet暗号鍵は別の秘密情報**。GitHub Repository Secretsなどで保管する設計候補だが、実登録はしない。鍵を失うと過去の暗号文を復元できないため、安全な**別保管先へのバックアップ**と回復手順が必要。
- GitHub Freeの非公開Repoでは、**Environment secretsや承認を求める環境保護ルールは基本的に使えない**。有料プランへの移行を前提にしない。Private Repoの**Repository secrets**は使えるが、同一Repoのワークフローから参照できるため、ブランチ・PR実行禁止・workflow変更のコードレビューを含めた権限管理が必須。
- GitHubのシークレット値のマスク機能は完全な漏えい防止ではない。ワークフローで秘密鍵、実ID、API応答原文を標準出力しない。外部の信頼できないActionsや依存コードに秘密情報を渡さない。
- Fernet暗号文はGit履歴に過去版が残り得る。あとから鍵が漏れると過去分も復号可能。Git履歴削除を通常運用の安全対策として頼らず、**秘密鍵の管理とリポジトリ権限**を優先する。コードに暗号鍵や実ファイルIDを埋め込まない。

## GitHub無料枠の判定（実数は未取得）

- GitHub FreeのPrivate Repoの利用目安は**2,000 Actions分/月**。アカウントの他のPrivate Repoでの実行と共有する。プランや請求方式・使用量によって実際の残枠は変わる。
- `actions_budget_guard.assess_private_actions_allowance` は**所有者がGitHub Billingから確認した数値**を受け取り、実行上限と**最低120分の予備**を差し引くドライラン評価。例：月30回×1回最大5分なら最大150分。残り無料枠が不明、使用数値が当月以外、予備を割り込む、課金停止ルールやシークレット管理が未確認の場合は**導入候補を保留**。
- 現在のGitHubコネクタにはこのアカウントのActions請求残時間を取得する専用操作がないため、**実際の使用量は未確認**。予算の「上限に達したら使用を停止する」設定を確認するまで、自動処理を有効にしない。既存ワークフローまで止まる可能性があるので、**予算設定自体も無断変更しない**。
- Free privateリポジトリで別途のEnvironment secretsが使えることを前提にした構成・GitHub Pro等の契約は**提案しない**。必要なら追加料金と無料代替を比較した上で別途承認を求める。

## 未完了事項

1. 実際のPrivate Repoの利用権限・GitHub Actionsの当月利用分・停止予算の確認。
2. 本番用Fernet鍵の秘密管理、バックアップ、紛失復旧、ローテーション手順。
3. Ed25519レビュー担当の本人認証、秘密署名鍵の安全な手元管理、署名を発行する承認操作。
4. 保存前のGoogle Drive更新版の再照合と、対象限定・手動起動・匿名サマリーだけのGitHub Actions試験。
5. Private GitHubによる暗号化済みであっても、取引先メタデータを保持してよいという所有者の確認。

上記を満たすまで、GitHubへの実チェックポイント書込み、Google OAuth/WIF権限変更、追加料金の発生するリソース作成、定期監視、自動仕入れ判断や発注は行いません。

## 公式の確認資料

- https://docs.github.com/en/billing/reference/product-usage-included
- https://docs.github.com/en/actions/concepts/billing-and-usage
- https://docs.github.com/en/billing/how-tos/set-up-budgets
- https://docs.github.com/en/actions/concepts/security/secrets
- https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments
- https://docs.github.com/en/rest/repos/contents
