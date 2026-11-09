# Private Reader用Python依存のハッシュ固定（2026-11-08、開発用）

## 実際に達成したこと

- 公開開発ブランチの `supplier_docs/private_runner_deps.in` に、Google Sheets APIクライアント・Google認証・X25519/AES-GCM用暗号ライブラリの**公開パッケージ3種類**を定義。
- 既存の**公開リポジトリの架空データPR CI**で`pip download --only-binary=:all:`により依存関係も含むLinux/Python 3.11向け**計22個の公開PyPI wheel**を取得し、実際に取得したファイルのSHA-256を計算。ここでは実Google認証、メーカー名、JAN、卸値、GitHub Secretsは使わない。
- バージョンとSHAを`supplier_docs/approved-requirements-hashed.txt`へ確定保存。公開CIの生成ログ：<https://github.com/gyallen0130/manufacturer-keepa-analysis/actions/runs/42448148805>。
- 非公開リポジトリへの**未設置テンプレート**`supplier_docs/templates/supplier-readonly.yml`のインストール手順を、`python -m pip install --require-hashes --only-binary=:all: -r manufacturer_checker/supplier_docs/approved-requirements-hashed.txt`へ変更。
- 公開PR CIは別の仮想環境において**ハッシュ照合付きインストール＋`pip check`＋重要な3モジュールのimport**まで成功。
- `private_dependency_lock.py`が固定バージョン／SHA256／公式PyPIだけを要求する構文を検査し、`private_workflow_integrity.py`が**テンプレートと実ロックファイルの両方**を検査するよう更新。浮動バージョン・異なるindex・重複・不明なインストールオプションを拒否。
- 最新のオフラインテストは**Python385件＋Node13件＝全398件**（Linux）。Windows復号系テストは別に継続。これは実Googleへの認証ではなくコード検査。

## 適用対象と制限

- 固定したのは**公開PyPIのLinux x86_64向けPython 3.11 wheel**の各1種類の実ファイルハッシュ。Windows、macOS、ARM、Python 3.12以降等に流用することは想定しない。プラットフォームが異なる場合、インストールは**失敗して停止する**のが望ましい。
- SHA-256一致は、取得したwheelのバイト列がレビューしたものと変わっていないという**同一性検査**であり、公開パッケージが無害か、作者や依存コードが信用できるかの証明ではない。
- 依存の最小化・SBOMやライセンス・脆弱性調査、GitHubアクションのコードレビューは別作業。GitHub-hosted runnerやPyPIのインフラストラクチャも利用しており、完全な隔離や供給元の正当性までは保証しない。
- **ハッシュ固定＝本番運用の許可ではない**。`private_workflow_integrity.py`の`eligible_for_separate_live_review`は「次の人手セキュリティレビューに進める」判定で、WIF資格情報・データ取得・請求設定・ユーザー復号の成功は示していない。
- 将来ライブラリ更新が必要になれば、`private_runner_deps.in`を変更 → 公開・合成データだけのCIで新しいwheelを収集 → 手動でpackage/releaseとwheelの差分を審査 → ハッシュを更新 → 隔離インストールと回帰試験を通す。**無承認で自動更新して運用しない**。
- このファイルとロックは公開ライブラリの名称・バージョン・ハッシュだけで構成され、顧客・仕入価格・実Sheet ID・秘密鍵は含まない。

## 現在も未完了の実稼働条件

1. 信頼できるPrivate GitHub実行リポジトリの権限制限、GitHub Actions利用額・Artifactストレージ請求・予算停止の確認。
2. 既存専用ReaderのGoogle Cloud WIF provider／IAMの**実設定の読み取り**。これはまだ実行されていない。
3. 実私有リポジトリでのWIF設定・GCP接続・**対象1ファイルだけの手動1回のSheets読み取り**。未実施。
4. Owner宛て暗号化Artifactの実受取・Windows実機での鍵管理／復号。未実施。
5. GitHubを入口にChatGPTが必要なメーカー情報を安全に参照できる認証済みチャネル。未完成。

**追加有料サービスの契約・Secrets登録・Google IAM変更・実Workflow実行・既存SP-API本番変更は今回ありません。**
