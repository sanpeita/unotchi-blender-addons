# CHANGELOG

## v1.5.0 — 2026-11-16

- `unotchi_torso_rig` **1.2.0**: 「ディフォルメ（△256）」モードを追加（`unotchi.torso_add_chibi`）
  - 箱14個＝168tri・23ボーン（VRM 1.0 humanoid）・1色・剛体ウェイト付き
  - 目と口は黒板顔アドオン（`unotchi_face_bars`）で後付けする設計。素体は眼球ボーン（leftEye / rightEye）だけ張る
  - 身長は `height_m` で指定（既定 1.2m）。左右対称・足裏接地・シェイプキーなし
  - テスト `unotchi_torso_rig_chibi.json`（2ケース）を含む3テストPASS
- 他の9本は変更なし（zip はビルドし直したためハッシュが変わっています）

## それ以前

- v1.4.0（VRMメタ / 黒板顔 / VRMボーン置換 / 自動リグ / トルソーver2）、v1.2.0（うのっち Forge）、
  v1.1.0（くねくねチェーン）、v1.0.x（初回公開）の履歴は [Releases](../../releases) を参照

## 未リリース

- なし
