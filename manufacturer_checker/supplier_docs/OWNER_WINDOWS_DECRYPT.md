# Windowsでメーカー情報を安全に開く操作（開発用・未導入）

**対象**：将来、専用Private GitHub Actionsからダウンロードした「利用者の公開鍵宛てに暗号化されたメーカー情報」。現在は実Google認証・Private GitHubでのArtifact作成・利用者Windowsへの配備・本物の鍵生成は実施していません。以下は準備済みのコードを説明する手順書であり、実運用開始の指示ではありません。

## 何を実装したか

- `owner_key_vault.py`：利用者端末上でX25519秘密鍵を生成し、**16文字以上のパスフレーズ**からScrypt（N=32,768、r=8、p=1）で導出した鍵とAES-256-GCMを使って暗号化した**ローカル保管ファイル**を新規作成する。秘密鍵の平文ファイル・Google秘密鍵・GitHub Secretsの登録は行わない。公開鍵（Base64）とSHA-256指紋だけを返す。
- `owner_result_cli.py` の `init-key`：新しい暗号化鍵保管ファイルを**一度だけ**作成。同名ファイルは絶対に上書きしない。パスフレーズはローカル対話端末の非表示入力で2回確認。
- `owner_result_cli.py` の `inspect`：受け取ったGitHubの暗号化ファイルを、自分の秘密鍵で**メモリ上だけで復号・検証**。メーカー名・JAN・仕入価格・ASINなどの詳細は画面に出さず、商品候補の件数などの匿名集計のみ表示。
- `owner_result_cli.py` の `export`：利用者が**明示的に危険性を理解して承認した場合だけ**、復号したメーカー情報を保護されたローカルフォルダに**新規JSONファイルとして保存**する。秘密の仕入価格・商品名・取引条件が平文になるため、共有／同期フォルダやGitHub／Colabへは保存しない。既存ファイル上書き禁止。
- パスフレーズやX25519秘密鍵をコマンドライン引数・GitHub Actions・環境変数・Colab・チャットへ渡さない。パイプやCIからの非対話実行を拒否し、失敗メッセージにパス・資料名・鍵・行データを表示しない。

## 導入前に必要な確認

1. WindowsのNTFSユーザーごとのアクセス許可と、BitLocker／デバイス暗号化が有効かを**利用者本人が確認**する。Pythonの `chmod` やCLIの承認フラグはWindowsのNTFS ACLやドライブ暗号化を保証しない。監査する機能は今後の課題。
2. `C:\PRIVATE-SUPPLIER-KEYS\` など、**クラウド同期されない、共有・UNCでない、本人のみアクセス可能なローカルフォルダ**を本人が用意する。これらは架空のパス例であり、今回実際に作成していない。
3. **Git管理フォルダ内は保存先として拒否**する。鍵・平文・取得した暗号文を開発リポジトリ配下に置かない。独立した長いパスフレーズを選び、暗号化された鍵保管ファイルと**パスフレーズを別々にバックアップ**する。両方の喪失時は過去のArtifactを復号できなくなる。暗号化された鍵保管ファイル自体も漏えいリスクがある。Keeper等の既存パスワード管理ツールを利用する場合は、保存・復元の権限と同期先の安全性を確認する。
4. `init-key` が返す**公開鍵とSHA-256指紋**は公開情報だが、初回は別の信頼できる方法で指紋を確認したうえでPrivate GitHubのVariablesへ登録する。公開鍵と指紋を同じGitHub画面で無断に変更できる管理者や悪意のあるWorkflowがいれば、暗号化する相手を差し替え得るので、コード・実行権限の保護は引き続き必要。
5. 実Google Sheetsのアクセスを確認するまでは、GitHubのPrivate Workflowの配置、WIF設定、Secrets、料金や課金停止の変更を行わない。**GitHub Freeの共有コンピュートクレジットとActions Artifact保存量は実アカウント分未確認**。

## Windows PowerShellでのコマンド書式（将来の操作例・実行はまだしない）

作業前に `manufacturer_checker` をカレントフォルダにして、Python 3.11、`requirements.txt` にある既存依存を利用する。

```powershell
# 初回：暗号化された鍵をローカルへ新規作成（本番開始前に所有者承認・ACL確認が必要）
python -m supplier_docs.owner_result_cli init-key --vault "C:\PRIVATE-SUPPLIER-KEYS\owner.vault"

# GitHubから受け取った暗号化Artifactを検証（結果の詳細は出力しない）
python -m supplier_docs.owner_result_cli inspect --vault "C:\PRIVATE-SUPPLIER-KEYS\owner.vault" --artifact "C:\PRIVATE-SUPPLIER-INPUT\owner-result.json" --trusted-fingerprint "<64桁の事前確認済み公開鍵SHA256>"

# 復号した機密JSONを書き出すときだけ、明示的な追加確認が必要
python -m supplier_docs.owner_result_cli export --vault "C:\PRIVATE-SUPPLIER-KEYS\owner.vault" --artifact "C:\PRIVATE-SUPPLIER-INPUT\owner-result.json" --output "C:\PRIVATE-SUPPLIER-OUTPUT\supplier-data.json" --trusted-fingerprint "<64桁の事前確認済み公開鍵SHA256>"
```

**パスフレーズはコマンドの後、ローカル端末に非表示入力で尋ねられます**。公開鍵・指紋以外の秘密情報をコードやコマンドの引数に書き込まない。

コマンドの実際の出力は、成功時の匿名集計（`inspect`）、公開鍵情報のみ（`init-key`）、ファイル作成可否のみ（`export`）。機密内容は `export` が作るローカルJSONファイルだけに保存される。

## なお残るリスク

- **GitHub Artifactの暗号化・復号成功は送信者本人の証明ではない**。X25519公開鍵を知る第三者でも新しい暗号文を生成可能。実際の仕入条件として信頼する前にGoogle Sheetの版と実行元Workflowを確認する必要がある。
- ローカルJSONは**完全な平文ファイル**。Windows ACL・BitLockerに加え、同期・インデックス・既定アプリの履歴・アンチウイルス検査・バックアップ等も保存先の選定に影響する。
- Scryptで暗号化していても弱いパスフレーズや端末マルウェアを守れるわけではない。鍵ファイルとパスフレーズの二重喪失で復元不能。鍵のローテーションと複数年の運用は未設計。
- ChatGPTがGitHubを通じて直接仕入データを検索・閲覧する**認証済みのチャネルは未完成**。現方式は利用者の手元で復号し、必要な情報を本人が確認する段階を目標にする。
- Windowsの実機でのACL/暗号化設定検証・実Artifactでの復号試験は未実施。GitHub CIで使う鍵・価格は架空・使い捨てのものだけ。

## 開発検証

```powershell
cd manufacturer_checker
python -m unittest discover -s tests -p test_supplier_owner_key_vault.py -v
```

この手順は新規有料サービスや新しいGoogle Cloudリソースを必要としないが、**本番運用に必要な既存環境の無料枠・課金設定は未確認**のまま。追加費用を生む操作は所有者の明示承認を要する。
