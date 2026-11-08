# 追加費用なしのオフラインバックアップ：Windows + Colab 開発手順

**状態：開発用コード・架空データのテストのみ。実際のWindows PCへの配置、暗号鍵発行、復旧アーカイブの作成、Google Drive/Private GitHubへの保存はまだ実施していません。**

## 結論

長期保存先は**本人管理のWindows PC上の保護されたフォルダと、別デバイス上の第二コピー**を候補とします。暗号化した承認履歴は `local_backup_store.py` で検証してから「新規作成のみ」で保存します。復旧用Fernet鍵はバックアップ本体とは別の保護された場所で管理し、実行端末が故障しても取り戻せる状態を要求します。

**Google Colabの標準ランタイムは永続保管先として使いません。** Google公式FAQでは、ランタイムVMは一定時間のアイドル後や最大寿命で削除されると説明されています。Colabでは架空データのテストや一時的な解析を行い、機密の鍵やバックアップはノートブック出力・共有セル・Google Driveの共有領域に残さないことが原則です。ローカルランタイムへの接続は実PCファイルへの権限を渡すため、使用前にコード・アクセス制御を確認してください。

## 操作前に確認すること

- **Windowsの保存先**：自分だけがアクセスできるフォルダを使用。**NTFS ACL、ドライブ暗号化（BitLocker／デバイス暗号化）、既存のバックアップ設定**を事前に確認する。ソフトウェアは、呼び出し時の `windows_storage_reviewed=True` で担当者の確認を要求するが、**ACLやBitLockerが有効かを実際に調査・設定する機能はない**。Windowsの `chmod(0600)` を信用してACLが安全になったとは扱わない。 ネットワーク共有（UNC）パスはローカル保存先として拒否する。OneDrive等の同期フォルダ・ネットワークドライブは無意識にアップロードされ得るため、明示的に選定するまで使用しない。
- **鍵の分離**：本番用の通常Fernet鍵／復旧用Fernet鍵／Ed25519署名秘密鍵は別用途。復旧用鍵をバックアップと同じPC・同じUSB・同じ共有フォルダに置かない。既存のパスワード管理ツールなどで別保管できるかを所有者が確認する。**鍵をチャット、公開GitHub、通常のColabセル・出力に貼り付けない**。
- **第二コピー**：別の物理デバイスまたは独立した保管先が必要。単に別フォルダに複製するだけではPC故障対策にならない。関数の `operator_confirmed_separate_device=True` は確認担当者の**申告**であり、実際にディスクが独立していることをプログラムが検証するわけではない。
- **作成元**：実際の監査チェックポイントが承認済みであることが前提。現状は実チェックポイントも発行・保管していないため、**本番バックアップを作る段階ではない**。

## コードと安全な実装

`supplier_docs.local_backup_store` はオフラインのローカルI/Oのみを行い、Google Cloud・GitHub・Drive・SP-API・Keepaに接続しません。関数はファイル名や取引先のIDをログ出力しません。

- `store_verified_local_backup(path, encrypted_archive=..., recovery_key=..., trusted_public_keys=..., approve_new_backup=True, windows_storage_reviewed=True)`：復旧アーカイブを復号・監査署名の検証後、**既存のファイルには一切上書きせず**暗号化したバイト列だけを保存。通常暗号鍵、復旧鍵、Ed25519秘密鍵のファイルは作らない。
- `read_verified_local_backup(path, recovery_key=..., trusted_public_keys=..., windows_storage_reviewed=True)`：保存済みの暗号文を読んで再検証する。破損、誤った鍵、承認署名の不一致、大きすぎるファイルなどは拒否。
- `copy_backup_to_separate_location(source_path, destination_path, recovery_key=..., trusted_public_keys=..., approve_independent_copy=True, operator_confirmed_separate_device=True, windows_storage_reviewed=True)`：元の暗号文と署名を確認してから第二の保存先へ**新規作成のみ**。同じフォルダ・同じ名前の既存ファイル・確認のないコピーを拒否。
- POSIX/Linux側の検査はディレクトリ0700・ファイル0600、シンボリックリンク拒否。Windows側のNTFS ACLやディスク暗号化は**コード上で安全性を証明できず、所有者の手動確認が必要**。Pythonの標準ライブラリだけではWindowsのジャンクションやアクセス権競合を完全には防げないため、信頼済みのローカル環境に限定する。
- 上記の関数には、秘密値をコマンドライン引数として渡すCLIを**用意していない**。将来のWindows操作画面や安全な入力方式を実装・レビューするまで、コードの直接実行は開発用とする。

**復旧する場合も、GitHub側の現在版・Google Driveの最新版を確認した後に、別工程で所有者が承認する必要があります。復旧処理がGitHubへ自動的に上書きすることはありません。**

## 架空データでのテスト

```powershell
cd manufacturer_checker
python -m unittest discover -s tests -p test_supplier_local_backup_store.py -v
```

WindowsのGitHub-hosted runnerとLinuxのPR CIで、**架空のファイルID・使い捨ての鍵・一時テストフォルダ**だけを使い、作成・再検証・上書き拒否・アクセス拒否・コピー・破損検知を試験します。テストの一時ファイルは試験終了後に削除され、実データ・シークレットはGitHubへ送られません。

## 続く判断

Windows上の実保護設定と物理バックアップ先、復旧鍵を別に保管する手段、承認署名の実本人認証が決まるまで、本番の保存・定期処理・GitHub書込権限付与は開始しません。追加の月額費用が必要なサービスや有料プランへの変更は所有者の明示承認が必要です。

公式資料：
- [Google Colab FAQ — 仮想マシンの寿命](https://research.google.com/colaboratory/faq.html)
- [Google Colab — ローカルランタイムのリスク](https://research.google.com/colaboratory/local-runtimes.html)
- [Microsoft — Windowsのデバイス暗号化](https://support.microsoft.com/ja-jp/windows/security/encryption/device-encryption-in-windows)
