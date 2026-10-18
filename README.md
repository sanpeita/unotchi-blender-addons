# うのっち Blender アドオン

VTuber・3D制作・デジタル教育の現場で使うために作った Blender アドオン集です。
Blender 4.2 以降（開発・検証は 5.2 LTS）で動きます。

## 収録アドオン

<!-- ADDONS:START -->
| アドオン | 何をする | パネル | 状態 |
|---|---|---|---|
| **メッシュ診断・一括修復** | 生成AIメッシュの非多様体・孤立頂点・ゼロ面積面・重複頂点・法線反転・スケール未適用を数え、1ボタンで直す。 | 3Dビューポート > N パネル > うのっち > Mesh Doctor | 合格 |
| **クネクネリグ自動生成** | 選んだメッシュに X/Y/Z 方向のボーン数を指定してアーマチュアを自動生成。頂点数に応じた上限つき。 | 3Dビューポート > N パネル > Rigging > クネクネリグ | 合格 |
| **雑リメッシュ（半減）** | 生成AIの高ポリメッシュを、形を崩しにくい順序で約半分に減らす。押すたびに段階的に半減する。 | 3Dビューポート > N パネル > Remesh > 雑リメッシュ | 合格 |
| **トルソー（ブロックマネキン）** | VRM1.x の humanoid ボーン名で二足22本／四足24本のアーマチュアを作り、各ボーンに「一辺＝ボーン長」の立方体メッシュを付ける。体型検討・ポージングの下敷き用。 | 3Dビューポート > N パネル > うのっち > トルソー | 合格 |
<!-- ADDONS:END -->
## インストール

[Releases](../../releases) から `.zip` をダウンロードして、
Blender で `編集 > プリファレンス > Get Extensions > Install from Disk` を選んで読み込ませます。
くわしくは [docs/install.md](docs/install.md)（日本語）/ [docs/install-en.md](docs/install-en.md)（English）。

## 動作環境

- Blender 4.2 以降（拡張機能パッケージ形式。検証は 5.2 LTS）
- OS は Windows で検証しています
- 外部ライブラリ・外部サービスへの依存はありません

## ライセンス

MIT（[LICENSE](LICENSE)）。自由に使えます。改造・再配布も歓迎します。

## 生成支援について

初稿のコード生成に AI（Backboard.io の Backboard Studio）を使い、そのあと人手でレビュー・
修正・検証を行って公開しています。検証は [addons/*](addons) ごとに用意したテストで実施しています。

## 開発（ビルド方法）

```powershell
# 各アドオンを拡張機能パッケージ（zip）にビルド → releases/ へ
python tools/build_all.py
```

個別にビルドする場合:

```powershell
cd addons/unotchi_mesh_doctor
blender --command extension build
```

## こまったとき

- 不具合・要望は Issues へ。Blender のバージョンと、`ウィンドウ > システムコンソール` の赤い文字を添えてください。
