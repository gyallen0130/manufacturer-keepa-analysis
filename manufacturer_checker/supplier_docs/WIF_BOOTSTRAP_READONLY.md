# Google Cloud WIF / Reader 初回の読み取り専用確認

更新：2026-11-09 JST ／ **開発コードのみ、実Google Cloud実行はまだしていない**

## 目的

GitHubの非公開共通知識リポジトリに本番ワークフローをまだ設置しておらず、`workflow_sha`や対象本番コミットの審査ができない状態でも、**Google Cloudの既存WIFプロバイダーと専用ReaderサービスアカウントのIAMポリシーを読めるか**を、所有者の既存Cloud Shellで確認するための最初の段階。

従来の厳格な`manual_wif_preflight_cli.py`は、本人のprivate settings JSON、レビュー済みworkflow SHA、Google Cloudからの実IAM読取、repoスナップショットが全部必要な**最終審査**。今回追加した`manual_wif_bootstrap_probe.py`は、その前段階の**存在と基本状態のチェックだけ**。成功してもWIFが安全だと断言しない。

## 新規コード
- [manual_wif_bootstrap_probe.py](manual_wif_bootstrap_probe.py)：既存の`gcloud_wif_readback.build_readonly_gcloud_commands`を呼び、検証済みの2操作`gcloud iam workload-identity-pools providers describe`と`gcloud iam service-accounts get-iam-policy`だけを実行する。Google IAM、Google Sheets、GitHubには**一切書き込まない**。
- [private_github_preflight_snapshot.py](private_github_preflight_snapshot.py)：認証済みChatGPT GitHub接続の`get_repo`と`branches/main`を、厳格な最終WIF監査が必要とする**PRIVATEのrepo/owner numeric ID、ブランチ保護状態**に安全変換。コード内ではGitHub APIを呼ばない。
- [架空テスト](../tests/test_supplier_manual_wif_bootstrap_probe.py)と[スナップショット架空テスト](../tests/test_supplier_private_github_preflight_snapshot.py)：初期状態で未承認のCloud読取が起きない、コマンドが固定、権限欠落・provider inactiveを保留にする、実ID・Reader email・OAuthエラーを標準出力に出さない、公開GitHubへ実IDをコミットしないことを検証。

## どの結果が得られるか

プロバイダーの存在、状態ACTIVE、disabled:false、OIDC issuerがGitHub、主要claimのマッピングがあること、ReaderのIAMポリシーが読めること、`roles/iam.workloadIdentityUser`の**何らかの**bindingがあることを、**boolだけ**出力する。

**これでは不十分**。binding先が正しい特定repo IDであるか、OIDC attribute conditionが特定の`repository_owner_id`／`repository_id`／`workflow_sha`／`sha`の両方に厳密に固定されているか、Readerの他IAM権限が安全か、GitHubの課金限度を設定しているか、すべて別の[厳密レビュー](PINNED_WIF_CONNECTION_REVIEW.md)が必要。検査で全Trueでも`production_connection_authorized: false`。

## 所有者がCloud Shellで安全に確認するときの手順（まだ実行していない）

**事前に**開発用プログラムと依存コードを独立レビューし、信頼できるCloud Shellでだけ実施。ChatGPTに秘密のプロバイダー名、サービスアカウント名、Googleアカウント名、IAM JSON、OAuthトークンを貼らない。Github public repo上に保存しない。

GitHubで**レビュー済みの特定コミット**を入手する（ブランチ名だけでチェックアウトするのは信頼境界として不十分）。コードには実メーカーの商品情報・原価を含めない。このブートストラップ検査はPython標準ライブラリと既存の読み取り専用`gcloud`を使用し、認証情報を新規発行しない。

**レビュー・チェックアウト後**、Cloud Shellのbashから：

```bash
cd manufacturer_checker
# 既存プロジェクトのWIF provider resourceと専用Readerを
# プライベートに入力する。-sで画面に表示せず履歴に残さない。
read -r -s -p 'Approved WIF provider (hidden): ' SUPPLIER_WIF_PROVIDER
echo
read -r -s -p 'Approved Reader service account (hidden): ' SUPPLIER_READER_SA
echo
export SUPPLIER_WIF_PROVIDER SUPPLIER_READER_SA
python -m supplier_docs.manual_wif_bootstrap_probe --confirm-readonly
unset SUPPLIER_WIF_PROVIDER SUPPLIER_READER_SA
```

上記の`read`はShellのヒストリーに入力値を保存しないが、**シェル環境変数自体がプロセスから見える可能性がある**ため、共有端末では実行しない。貼り付けるべきものは**匿名のchecksのTrue/Falseとstatusだけ**。何も自動有効化しない。

**実認証が利用できない場合**は、失敗のみが分かる`blocked_cloud_bootstrap_not_verified`を返す。エラーの元Google URL／プロジェクト名／アカウント情報を表示しない。

## GitHub Billingの別途確認（未実施）

GitHubの`https://github.com/settings/billing`内で**ActionsおよびArtifacts**の使用量、製品・リポジトリ別の予算、上限到達後の利用停止を確認する。通知アラートだけでは従量課金を止めない。公式：[GitHub budgets and alerts](https://docs.github.com/en/billing/how-tos/set-up-budgets)。設定変更・課金プラン変更は所有者の別途明示承認まで行わない。**本検査はGitHub Billing APIに接続しない**ので、成功しても費用安全性を主張できない。

## 今回明らかにした制約と次の工程

1. 現ChatGPTアプリには**Google Cloud IAMの実状態を直接読む接続がない**。GitHub private Repoは存在、main未保護、Reader共有済みの実Google Sheets 2件があるが、Cloud側WIF ProviderとSA IAMは未確認。本モジュールもこの会話ではGCPへ接続しない。
2. Cloud Shellでの最初の実読取が成功した後、**実プロバイダーの条件全文とReader IAMのbindingを、PRIVATEで厳格な既存`manual_wif_preflight_cli`に渡して審査**。レビューされたworkflow/source SHAが整う前にtoken交換しない。
3. GitHub Private repo用の本番workflowと暗号化された成果物の受信、オーナー復号、料金・IAM、コードの供給元検査まで完了してから**対象1ファイルの`files.version`だけ**を試す。112社・200行超の自動検索はその後。

**ChatGPT優先／Claude未導入／新有料サービスやIAM/Secrets変更なし。**
