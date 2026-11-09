# Windows用・復旧鍵をログに残さないローカルバックアップ検証（開発用）

**段階：公開開発リポジトリのコード／架空データ試験のみ。実ユーザーのWindowsに配置しておらず、取引先の実バックアップや復旧鍵は作成していません。自動実行・Google API・GitHub書込は行いません。**

## できること

`supplier_docs.local_backup_cli` は、**実際のPCでの操作前にレビューを要する**対話式CLI試験版です。既存の暗号化済み監査アーカイブを検証し、必要なら「明示承認を得た、別の物理媒体」と申告された場所にコピーすることだけを目的とします。

- `verify`：暗号化アーカイブの復号・全Ed25519承認署名の検証。書込みなし。
- `copy`：検証後に暗号化アーカイブを指定先へ**新規作成のみ**でコピー。既存ファイルは上書きしない。
- 実行時に`getpass`による復旧用Fernet鍵の**非表示入力**を行い、`--key`や`--password`などの引数は受け付けない。**秘密鍵をコマンドライン、スクリプト、環境変数、公開Colabセル、GitHubログや標準出力に書かない**。
- 非対話実行／パイプからの秘密鍵入力は拒否。エラーは経路や機密値を含まない定型メッセージを表示し、成功しても確認済み履歴サイクル件数だけを表示。
- 信頼済みレビュアーの**公開鍵だけ**を持つ別のローカルJSONファイルを読み、事前に独立した方法で確認した**SHA-256指紋**と比較する。キーリングに載っている値自身から同じ指紋をコピーしても、本人認証にはならない。秘密署名鍵・通常の暗号鍵は読み込まない。

## 実行前に必要な構成

以下は構文と手順の**参考**です。実際のバックアップ、独立した指紋、復旧鍵、安全な保存先、認証済み承認者公開鍵の準備が整うまで**実行しないでください**。

1. 既存Windows端末のフォルダがローカルNTFSで、本人のみのアクセス権・BitLocker／デバイス暗号化の状態が安全であることを確認する。本コードは**これらを自動確認・設定しない**。UNCネットワーク共有への保存を拒否し、OneDrive等の同期フォルダを避ける。
2. レビュアー本人の署名公開鍵を**信頼できる別経路で本人確認**し、ローカルに専用ファイルを準備する。ファイル形式は `{"schema_version":"supplier-trusted-reviewers-v1","reviewers":{"reviewer_01":"<32-byte Ed25519 raw public key, base64>"}}`。このサンプルは**架空の書式**であり、実鍵は含まない。公開鍵JSONのSHA-256指紋を**別の信頼済み保管先**に記録する。
3. 暗号化された復旧アーカイブ本体と、その復号用Fernet復旧鍵は**別の保管場所**に分離する。復旧鍵をテキストファイルでこのフォルダに置かない。パスワード管理ツール等から直接非表示入力欄へ貼り付ける際も、**クリップボード履歴・画面録画・キーロガー等から漏れない保証はない**。
4. 実環境の作業者が操作を理解した上で手動実行する。確認を求められたら、Windows保護設定は `WINDOWS-REVIEWED`、別物理媒体は `SEPARATE-DEVICE`、新規コピーのみは `COPY-ONCE` とタイプする。**文字入力は自動確認の代替ではない**。

```powershell
# これはコマンドの書式例であり、実際の鍵や実取引先情報は記載しない
cd manufacturer_checker
python -m supplier_docs.local_backup_cli verify --source "C:\PRIVATE-BACKUP\backup.enc" --public-keyring "C:\PRIVATE-KEYRING\reviewers.json" --trusted-keyring-sha256 "<信頼済み公開鍵JSONの64桁SHA256>"
python -m supplier_docs.local_backup_cli copy --source "C:\PRIVATE-BACKUP\backup.enc" --destination "E:\ISOLATED-BACKUP\backup-copy.enc" --public-keyring "C:\PRIVATE-KEYRING\reviewers.json" --trusted-keyring-sha256 "<信頼済み公開鍵JSONの64桁SHA256>"
```

**復旧用Fernet鍵を含むコマンドライン引数は一切存在しません。** 実行中に別途、非表示入力が現れます。標準ライブラリの `getpass` はターミナル入力を隠しますが、メモリダンプ・マルウェア・クリップボード・親プロセスからの監視を防ぐものではありません。重要な操作は**信頼できるローカルの対話式ターミナル**だけで行い、リモートCI・無人実行には使用しません。

## この段階で意図的にできないこと

- 初回の実バックアップ発行・復旧鍵生成・通常鍵ローテーション・Ed25519の実本人認証・秘密署名鍵の登録。
- 復号データをディスクに出す、GitHubの保存先を更新する、Google SheetsやAmazonへ書き戻す、自動再実行する。
- NTFS ACL／BitLocker／実媒体の独立性を自動監査する。
- 独立したキーリング指紋が作れないときに信頼の問題を無視して実行する。

## 開発用の架空データ試験

```powershell
python -m unittest discover -s tests -p "test_supplier_local_backup*.py" -v
```

既存のGitHub Actions（Linux／Windows）で、復旧鍵の非表示入力を**偽の関数に置き換えて**テストします。暗号鍵・署名鍵は毎回破棄する架空の鍵で、実PCからの情報・GitHub Secrets・Google Driveの実IDは使用しません。実ユーザーの端末ではまだ検証していません。

**費用方針：追加の有料アプリ・有料GitHubプラン・クラウドリソースは導入しません。**
