# Install & Usage (English)

## Easiest way: add the repository (recommended)

Register this repository in Blender and you can install from a list and **receive automatic updates**.

1. Open `Edit > Preferences > Get Extensions`
2. Use the `Repositories` dropdown at the top right -> `+` -> **Add Remote Repository**
3. Paste this URL:

   ```text
   https://unotchi.com/unotchi-blender-addons/repository/index.json
   ```

4. Give it any name (e.g. `unotchi add-ons`) and confirm. The list will show "Unotchi ..."
5. Press **Install** next to the add-on you want

> A plain GitHub repository URL (like `https://github.com/...`) does **not** work here.
> Blender reads the `index.json` above. If it fails, remove the wrong repository with the
> `-` button and add this one instead.

---

## Installing from a zip

<!-- TODO(release): add one screenshot per add-on. Avoid heavy GIFs. -->

## 1. Download

Download the `.zip` for the add-on you want from [Releases](../../releases).
Do not unzip it — Blender reads the archive directly.

## 2. Install into Blender

1. Start Blender
2. Open `Edit > Preferences > Get Extensions`
3. Use the top-right dropdown and choose **Install from Disk**
4. Select the downloaded `.zip`
5. Enable the add-on in the list

Tip: you can also drag and drop the `.zip` onto a Blender window.

## 3. Find the panel

| Add-on | Location |
|---|---|
| Mesh Doctor | 3D Viewport > N panel > うのっち > Mesh Doctor |
| Auto Snake Rig | 3D Viewport > N panel > Rigging > クネクネリグ |
| Zatsu Remesh | 3D Viewport > N panel > Remesh > 雑リメッシュ |

(Press `N` in the 3D Viewport to open the N panel.)

## 4. If something goes wrong

- The add-on does not appear: check your Blender version (4.2+) and that the zip is not unpacked.
- An error appears: open `Window > Toggle System Console`, copy the red text and paste it into an Issue.
