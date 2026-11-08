# メーカー詳細情報を利用者に渡す暗号化ファイル（開発用・未運用）

## なぜ必要か

GitHubからGoogle Sheetsを読み取れても、**仕入価格・JAN・ASIN・契約条件・ファイルIDをGitHub Actionsのログに直接表示するのは不適切**。一方、匿名集計だけでは「GitHubを入口にメーカー情報を必要時に参照する」という目的を満たせない。

そこで `private_result_envelope.py` と `private_result_file.py` を追加し、解析されたprivateな詳細情報を**利用者の公開鍵で暗号化したファイル**として取り出す構成を試作した。

**現在は架空データの試験だけで、GitHubのPrivate Actions、Google WIF、実メーカー資料、利用者の実暗号鍵は一切使用していない。**

## 暗号化の方式と境界

- **X25519**：利用者だけが持つ秘密鍵と、GitHub側に配置してよい利用者の**公開鍵**で共有秘密を得る（ランダムに生成した使い捨て送信側秘密鍵を各処理で廃棄）。
- **HKDF-SHA256**：ランダムsaltとアプリケーション識別子から暗号鍵を導出。
- **AES-256-GCM**：原文のメーカー名・卸価格・JAN/ASIN・シートID・タブ名・レビュー注意コードをメモリ上で認証付き暗号化。バージョン、受信者公開鍵のSHA-256指紋、送信者一時公開鍵、nonceなどのヘッダーも認証対象とする。
- アップロード候補の中身は暗号化されたJSONエンベロープだけで、**一切の平文解析結果や復号用秘密鍵を含めない**。ファイル上限・入力形式・認証タグを検証する。
- **公開鍵のSHA-256指紋を別経路で本人確認**した上でRunnerへ設定する。公開鍵と指紋を同じ場所にセットすれば、両方同時に差し替えられるリスクはある。公開鍵の差し替えを完全に防ぐためには、対象Private Repoの設定変更権限・ワークフローコード・Google WIF信頼条件を別途強化する必要がある。
- 暗号文の正しい復号には、利用者のローカル端末だけで保持するX25519秘密鍵が必要。この秘密鍵を**GitHub Repository Secrets、Google Colabノートブック、公開リポジトリ、ChatGPTチャットに渡してはいけない**。
- **重要**：受信者公開鍵を知る第三者も形式上は新しい暗号文を作成できる。この方式は原文の秘匿と暗号文改ざん検出を目的とし、**送信元が本物のGoogle Driveデータであることを独立に証明しない**。実運用ではGitHub実行・コードの出所・対象シート版の検証が別途必要。

## Github Actionsへの配置候補（有効化していない）

非公開リポジトリに、所有者が審査したコードと `supplier-readonly.yml` テンプレートを導入した場合の想定：

1. `workflow_dispatch`（手動）起動以外は拒否。GitHub標準Runner、短時間のWIF認証、閲覧専用Google Sheetsスコープを使う。
2. Private `SUPPLIER_READ_MANIFEST_JSON` で最大3 Sheets・各4タブ・合計7,200セルの範囲を指定。サービスアカウントには事前に許可されたSheetsだけを共有。
3. `SUPPLIER_PRIVATE_RESULT_MODE=owner_encrypted_artifact`、本人が検証したX25519公開鍵 `SUPPLIER_RECIPIENT_PUBLIC_KEY_B64` とその指紋 `SUPPLIER_RECIPIENT_KEY_FINGERPRINT_SHA256`（**公開情報**）を設定。
4. マニフェスト・公開鍵の指紋を読み取り前に検証。既存パーサーで機密詳細を**メモリにのみ**展開してから、利用者の公開鍵で暗号化する。
5. 暗号文だけを、Runnerの `RUNNER_TEMP/supplier-owner-encrypted-result.json` に新規作成し、GitHub Actionsの公式 `actions/upload-artifact@v4` に渡す。元の資料は編集しない。ログには匿名件数のみ。
6. アーティファクト名は `supplier-owner-encrypted-result`。**保持期限1日**を指定し、長期的な保存先には使わない。毎回「必要なときに手動で再実行し、ダウンロードする」想定。
7. 利用者の信頼済みローカル端末で秘密鍵を使ってファイルを復号する。**ローカル鍵の安全な発行・保存・バックアップと、利用者向けの安全な復号操作UIは未実装**。今は `open_private_inspections(...)` の開発用関数だけである。

公開GitHubリポジトリ内のテンプレートは `manufacturer_checker/supplier_docs/templates/supplier-readonly.yml` に置かれており、**有効な `.github/workflows` 配下には移動していない**。実在Private Repoのworkflow・Secrets/Variables・Google WIF・Reader権限は無断変更しない。

## 無料枠と保存上のリスク

- GitHub Actionsの標準Runner計算使用量およびArtifacts保存容量・帯域等が**アカウント共有の課金対象となる可能性**がある。実際の当月使用額と支出停止設定を確認するまでこのテンプレートは**導入しない**。新たな有料プランや有料クラウドを前提にしない。
- GitHubのArtifactsは保持期限内だけ利用できる一時ファイル。今回の1日保持は長期保存・永続参照の代替ではない。厳密な常時可用性が必要なら、同じPrivate認証下での都度取得・安全な結果配信UIなど別設計が必要。
- 暗号化済みでも、GitHub Actions側のコード改ざん・未保護の実行ブランチ・Google WIFプロバイダー設定ミス・Google Sheetsへの過剰権限から**原資料の機密が漏れる可能性**は残る。現状の未保護Private Repoを、そのまま実稼働用の信頼境界とは扱わない。
- ChatGPTから暗号化済みArtifactへアクセスできたとしても、**復号秘密鍵をChatGPTに共有しない限り詳細は読めない**。チャットに秘密鍵を貼る方式は採用しない。所有者のローカル復号または別の安全な認証済み連携手段が必要。

## テスト

`test_supplier_private_result_envelope.py`：鍵を間違えたときの復号拒否、暗号文・ヘッダー改ざん検出、暗号文のみの保存、上書き拒否、大量データ拒否、シンボリックリンク拒否（Linux）などのオフライン試験。

`test_supplier_on_demand_reader.py`：架空のGoogle API値をもとに**卸価格を含むprivate解析結果だけが暗号化ファイルに入ること**、ログには件数しか出ないこと、公開PRイベント／公開鍵指紋の不一致／保存先未指定／既存暗号文の上書きを拒否することを確認。

いずれも実Google API通信・実GitHub Secrets・実サプライヤーデータなし。

## 現状の運用判定

**Go（開発・架空テストのみ）**：指定範囲の読取・解析 → 利用者公開鍵に暗号化 → Runner一時保存先に暗号文だけ新規保存 → 匿名件数をログ表示、という一連の処理コード。

**No-Go（本番）**：実GitHub WIF認証、Private Repoの実行コード保護、閲覧権限の実確認、実1ファイルの手動読み取り、当月の課金確認、所有者X25519秘密鍵の安全な保管・復号操作、ChatGPTまでの安全な配信方法。
