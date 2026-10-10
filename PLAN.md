# ro-render

A Roblox Studio plugin that frames a selected model, then sends it to Blender for a high-quality cutout render. Blender applies the portrait effects and writes a PNG into a folder you choose. The file name is the subject's name.

The Studio widget is for choosing the subject, aiming the camera, editing effects, previewing the real render, and saving that setup so the next subject can reuse it. Blender produces the pixels. The place camera never moves while you frame.

## What you do

1. Start Blender with the bridge add-on enabled. It listens on `http://127.0.0.1:28082`.
2. In Studio, select a `Model`, `BasePart`, `Folder`, or a set of parts, then click **Use selection**. The viewport shows that subject.
3. Orbit, pan, and zoom, or type camera orientation, camera position, and FOV, until the framing is right.
4. Set the effects. Example: stroke thickness `5`, stroke color black (`#000000`), FOV `60`, output `512×512`.
5. Set the output folder once. It stays until you change it.
6. Click **Preview**. The widget shows the composited image (stroke, glow, shadows, background) and does not write the final file.
7. Name the configuration, click **Save**, then click **Render**.
8. The file is `{folder}/{SubjectName}.png`.
9. Select another character and click **Use selection**. The file name becomes that character's name. Choose the saved configuration from the dropdown. Camera, effects, and output size come back. Click **Render** again.

No command bar. No `require`. The widget is the whole workflow.

## What a configuration stores

Loading a configuration applies it to whatever subject is in the viewport. It does not swap the subject, and it does not rename the file.

| Saved in the configuration | Remembered on its own | Taken from the current subject |
| --- | --- | --- |
| Camera orientation (yaw, pitch, roll) | Output folder | File name, defaulting to the subject's name |
| Camera position: focus offset from the subject pivot, plus distance | | |
| FOV | | |
| Output width and height | | |
| BackgroundColor, backgroundTransparency | | |
| StrokeThickness, StrokeColor | | |
| DropShadow, InnerShadow, OuterGlow, InnerGlow | | |

The camera is stored relative to the subject pivot. The same yaw, pitch, distance, and focus offset land on the next character in the same way, wherever that character sits in the place.

Configurations persist with `plugin:SetSetting` as a JSON string from `HttpService:JSONEncode`. Tables stored directly are not reliable across Studio versions. Settings are per user, on this machine, and they apply in every place.

Setting keys:

- `RoRender_Presets_v1` — the configuration map
- `RoRender_OutputDirectory` — the folder path

Dropdown behavior:

- The closed control shows the last chosen name, or **No configuration**.
- Opening it shows a `ScrollingFrame` of names, sorted alphabetically. Clicking a row loads that configuration onto the fields and the viewport camera, then closes the list.
- **Save** writes the current camera, effects, and output size under the name in the text box. An existing name is overwritten, and the status says it was updated.
- **Delete** removes the name currently shown in the dropdown.
- An empty name does not save. The status asks for a name.
- Loading refreshes camera, effects, and size. It leaves the file name and the output folder alone.
- Loading never moves the Studio camera.

### Stored shape

```lua
{
  name = "Hero",
  yaw = 0.785,                 -- radians, around world up
  pitch = -0.436,              -- radians
  roll = 0,                    -- twist around the look axis
  distance = 14,               -- studs from the focus point
  fov = 60,
  focusOffset = {0, 0, 0},     -- object-space offset from the subject pivot
  width = 512,
  height = 512,
  backgroundColor = {1, 1, 1}, -- 0–1 RGB
  backgroundTransparency = 0,  -- 0 solid, 1 fully transparent
  strokeThickness = 5,         -- pixels at the output size; 0 draws no stroke
  strokeColor = {0, 0, 0},
  dropShadow = {
    enabled = false,
    color = {0, 0, 0},
    opacity = 0.45,
    offsetX = 6,
    offsetY = 6,
    blur = 10,
  },
  innerShadow = {
    enabled = false,
    color = {0, 0, 0},
    opacity = 0.5,
    offsetX = 4,
    offsetY = 4,
    blur = 8,
  },
  outerGlow = {
    enabled = false,
    color = {1, 1, 1},
    opacity = 0.8,
    size = 16,
  },
  innerGlow = {
    enabled = false,
    color = {1, 1, 1},
    opacity = 0.6,
    size = 12,
  },
}
```

Shadow and glow defaults are off. A new configuration is a plain subject on a white background until you turn something on.

Distance is stored in studs, as set. **Fit** recomputes distance from the current subject's bounding radius. Loading a configuration applies the saved stud distance, so two characters of similar size keep the same framing. A much larger subject may need **Fit** or a distance edit afterwards.

## Effects

These are flat portrait effects on a cutout, in the same family as a stroke around a character icon. Blender renders the subject with a transparent film, then a compositor stacks the effects. Preview and Render use that same compositor, so the preview matches the file.

Back to front:

1. **BackgroundColor**, with alpha `1 - backgroundTransparency`. Transparency `0` is solid. Transparency `1` leaves the background fully transparent. Glow and shadow pixels still appear when the background is transparent.
2. **DropShadow** — a copy of the silhouette, offset by `offsetX` / `offsetY` pixels, blurred by `blur`, colored, and composited behind the subject at `opacity`.
3. **OuterGlow** — the silhouette blurred by `size` pixels, colored, behind the subject.
4. **StrokeThickness** and **StrokeColor** — the silhouette expanded by that many pixels, with the original shape cut out, filled with the stroke color. Thickness `0` draws no stroke.
5. The subject.
6. **InnerGlow** — a colored falloff inside the silhouette, `size` pixels wide.
7. **InnerShadow** — a darkened falloff inside the silhouette.

Stroke thickness is in output pixels. A thickness of `5` at `512×512` is 5 pixels on the file. A smaller preview scales thickness, offsets, blur, and glow size by `previewLongSide / outputLongSide` so the visual weight matches.

Lighting is a fixed three-point studio rig in Blender (key, fill, rim). It is the same for every configuration, so a saved setup does not silently change the shading. Materials are approximated from the Roblox material: Plastic, Metal, Neon, and the rest as a principled shader with the part color. Neon is emission.

## Camera

The viewport camera and the Blender camera share one rig. Saving a configuration stores the rig.

Focus in subject space is `pivot * CFrame.new(focusOffset)`. The camera sits `distance` studs back along the orbit direction, looks at the focus, then applies roll. Yaw and pitch use `CFrame.fromEulerAnglesYXZ`.

| Control | Writes |
| --- | --- |
| **cameraOrientation** | Yaw, pitch, and roll, shown in degrees, stored in radians. Pitch clamped to about ±89°. |
| **cameraPosition** | Focus offset X/Y/Z from the subject pivot, in studs, plus distance. The camera always looks at that focus, so a reused configuration stays aimed at the subject. |
| **FOV** | Vertical field of view on both cameras, clamped to 1–120. |

| Gesture | Effect |
| --- | --- |
| Left drag | Yaw from horizontal mouse movement, pitch from vertical. |
| Right drag | Moves `focusOffset` along camera right and camera up. |
| Wheel | Multiplies `distance` by 0.9 or 1.1. Minimum distance is a small fraction of the bounding radius so the camera cannot pass through the pivot. |
| Field of view | Sets `Camera.FieldOfView` on the viewport camera. |

**Fit** (beside the viewport) frames the current subject: bounding-box center as focus, 30° FOV, distance = `radius / tan(fov/2)`, yaw 45°, pitch −25°, roll 0. That is also the view the first time a subject is shown.

The viewport clone is for aiming only. `ViewportFrame` lighting does not match the Blender render. A line under the viewport says that. The **Preview** image is the one that matches the file.

Blender receives the camera already expressed in subject-local space, with the subject at the origin. Roblox is Y-up. The scene is sent as glTF-style data so Blender's axis conversion happens once, on import.

## Preview, then render

- The viewport is for aiming. It updates while you drag.
- **Preview** asks Blender for a fast EEVEE image. The long side is 512, or the output size when that is smaller. The widget shows it and does not write the final file. Changing the camera, an effect, or the output size marks that image out of date until you preview again.
- **Render** asks Blender for the exact width and height and writes the PNG. Final quality is Cycles at 128 samples. The widget polls the job until it finishes, so a longer render is not cut off by an HTTP timeout. The button reads **Rendering…** and ignores further clicks.

The preview image comes back as packed RGBA bytes (base64 in JSON). The plugin builds an `EditableImage` with `AssetService:CreateEditableImage` and `WritePixelsBuffer`, then assigns it with `Content.fromObject` on an `ImageLabel`. Studio plugins can use these APIs in edit mode.

Width and height are integers from 16 to 4096. The default is 512×512. Output size is independent of the Studio window.

## Output path

The folder box is an absolute directory. It is stored in `RoRender_OutputDirectory`, separate from configurations.

On render, the bridge writes `{folder}/{fileName}.png`. The file name box defaults to the sanitized subject name when you click **Use selection**. You can edit it before rendering. Loading a configuration does not change it, so the second character keeps its own name.

The bridge creates the folder if it is missing. An existing file of the same name is overwritten. The status line shows the full path. Invalid characters in the file name are replaced the same way as a filesystem-safe slug: anything outside letters, digits, `-`, `_`, and `.` becomes `_`. An empty name becomes `render`.

## Widget

A toolbar button, **ro-render**, toggles a `DockWidgetPluginGui` docked to the right. Default size is about 360×720, minimum about 320×480. The form sits in a `ScrollingFrame` because the effect controls do not fit on one screen. The widget is built with `Instance.new`.

Top to bottom:

1. **Subject row.** Name of the current selection, and **Use selection**. The widget also listens to `Selection.SelectionChanged` while it is open, and updates the label. The clone updates only when **Use selection** is clicked.
2. **Viewport.** A square `ViewportFrame` with a `WorldModel`, a `Camera`, and the cloned subject. Ambient is high enough that the preview reads clearly.
3. **Fit**, and the drag hint: left-drag orbit, right-drag pan, wheel zoom.
4. **Camera fields.** FOV, yaw, pitch, roll, distance, focus offset X/Y/Z. Each field commits on focus loss.
5. **Effects.** Background color as hex (`#FFFFFF`), background transparency, stroke thickness, stroke color. Then DropShadow, InnerShadow, OuterGlow, and InnerGlow, each with an enable toggle and its fields.
6. **Configurations.** Dropdown button, name box, **Save**, **Delete**.
7. **Output.** Folder path, width, height, file name.
8. **Preview** and **Render**.
9. **Preview image.** Hidden until the first successful preview. Shows the last Blender result. A muted line says when it is out of date.
10. **Status.** Idle, working, saved path, or a specific error.

Empty selection shows a short line in the viewport: select a model in the Explorer, then click Use selection.

Colors are hex text boxes. There is no Studio color-picker dialog to call from a plugin.

## Getting the subject into Blender

The plugin clones the selection and records each visible part at its current CFrame relative to the subject pivot. That keeps the pose on screen, including Motor6D poses. The real place is not moved.

| Instance | What Blender builds |
| --- | --- |
| `Part`, `WedgePart`, `CornerWedgePart`, cylinder and sphere shapes | A matching primitive scaled to `Size`, with color, material, and transparency |
| `MeshPart`, `SpecialMesh` | The real mesh, plus texture when it has one |
| Accessory handles | The handle mesh, placed at its pivot-relative CFrame |
| `Decal`, `Shirt`, `Pants`, `SurfaceAppearance` | Texture images when the id can be read |

Skipped: `Script`, `LocalScript`, `ModuleScript`, `Humanoid`, `Attachment`, and anything that is not geometry.

Mesh bytes are read in Studio with `AssetService:CreateEditableMeshAsync` when the place can read that mesh, then posted to the bridge as binary (float32 positions, normals, uvs, and indices) in a follow-up request per mesh. The scene JSON itself stays small and only references those mesh ids. If the EditableMesh read fails, the bridge downloads `https://assetdelivery.roblox.com/v1/asset/?id=`. If both fail, Render stops and names the part.

`UnionOperation` parts that expose no mesh are sent as a box of their bounding size, and the status says so.

Wrap-deformed layered clothing is later work. This version places each mesh where it sits and does not re-solve wrap cages. Shirt and pants templates are applied when their image ids can be read; custom body UVs use the mesh's own texture.

Every cloned instance must be `Archivable`. If a clone would drop descendants, the action stops and names the instance.

### Scene body

`POST /preview` and `POST /render` send:

```json
{
  "subjectName": "MyCharacter",
  "fileName": "MyCharacter",
  "output": { "directory": "C:/renders", "width": 512, "height": 512 },
  "camera": {
    "position": [0, 2, 14],
    "target": [0, 2, 0],
    "up": [0, 1, 0],
    "fov": 60
  },
  "effects": {
    "backgroundColor": [1, 1, 1],
    "backgroundTransparency": 0,
    "stroke": { "thickness": 5, "color": [0, 0, 0] },
    "dropShadow": { "enabled": false, "color": [0, 0, 0], "opacity": 0.45, "offset": [6, 6], "blur": 10 },
    "innerShadow": { "enabled": false, "color": [0, 0, 0], "opacity": 0.5, "offset": [4, 4], "blur": 8 },
    "outerGlow": { "enabled": false, "color": [1, 1, 1], "opacity": 0.8, "size": 16 },
    "innerGlow": { "enabled": false, "color": [1, 1, 1], "opacity": 0.6, "size": 12 }
  },
  "parts": [
    {
      "name": "Head",
      "class": "MeshPart",
      "cframe": [1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 1.5, 0],
      "size": [1.2, 1.2, 1.2],
      "color": [0.9, 0.8, 0.7],
      "material": "Plastic",
      "transparency": 0,
      "meshRef": "mesh-1",
      "textureRef": "tex-1"
    }
  ]
}
```

`cframe` is twelve numbers, rotation then translation, relative to the subject pivot. Camera `position`, `target`, and `up` are in that same space. FOV is vertical, matching Roblox.

## Bridge

A Blender add-on, started from a panel in the 3D View sidebar, runs a localhost server on `127.0.0.1:28082`. `bpy` only runs on Blender's main thread, so the HTTP thread queues jobs and a `bpy.app.timers` callback executes them.

| Request | Result |
| --- | --- |
| `GET /health` | `{ "ok": true }`. The widget calls this when it opens and before Preview or Render. |
| `POST /preview` | Queues an EEVEE render. Responds when the image is ready: `{ "ok": true, "width", "height", "rgbaBase64" }`. |
| `POST /render` | Queues a Cycles render. Responds immediately with `{ "ok": true, "jobId" }`. |
| `GET /jobs/{id}` | `{ "status": "running" }`, or `{ "status": "done", "path" }`, or `{ "status": "error", "error" }`. |
| `POST /mesh` | Stores one mesh payload (`meshRef`, base64 vertices and indices) for the next job. |
| `POST /texture` | Stores one image payload (`textureRef`, base64 PNG or the original bytes). |

Preview uses EEVEE so it returns in a few seconds. Render uses Cycles, 128 samples, transparent film, PNG with RGBA. The compositor node tree is built from the effects block and is shared by both jobs. Preview scales pixel effects as described above. Render uses the pixel values as entered.

The widget polls `GET /jobs/{id}` about twice a second. On success the status shows the full path. On failure it shows the bridge error, shortened to one line.

Plugin `HttpService` calls go to `127.0.0.1`. A local plugin can do that without the place's Allow HTTP Requests setting. The first run of a non-local plugin will ask the user to allow that host.

If Blender is not running, the status says to start the bridge on port 28082. The place is left unchanged.

## Errors the widget must surface

| Condition | Status text |
| --- | --- |
| Nothing selected | Select a model or part. |
| Instance not archivable | "`Name` is not archivable, so it cannot be cloned." |
| Bridge down | "Blender bridge is not running. Start it on port 28082." |
| Mesh unreadable | "Could not read the mesh on `Name`." |
| Union fell back to a box | "Union `Name` was sent as a box." |
| Bad output size | "Width and height must be between 16 and 4096." |
| FOV out of range | "Field of view must be between 1 and 120." |
| Empty configuration name | "Enter a name to save this configuration." |
| Render job error | The bridge's error line. |
| Preview out of date | "Preview is out of date." |

## Project layout

Luau sources, built into a local plugin with Rojo. The Blender add-on lives beside them and is installed into Blender separately.

```
src/
  Plugin.server.luau     toolbar, dock widget
  Widget.luau            dock UI, viewport, preview image, dropdown
  CameraRig.luau         yaw / pitch / roll / distance / focus math
  PresetStore.luau       JSON load and save through plugin:SetSetting
  SubjectUtils.luau      selection, clone, file names
  SceneExport.luau       parts, meshes, and textures into the scene payload
  Bridge.luau            health, preview, render, job polling
blender/
  ro_render/
    __init__.py          add-on registration and sidebar panel
    server.py            HTTP server and job queue
    scene.py             build objects, camera, and lights from the payload
    compositor.py        background, stroke, shadows, glows
    mesh_import.py       primitives, packed meshes, and assetdelivery fallback
default.project.json     Rojo plugin project
README.md
```

`Plugin.server.luau` is the only script that touches `plugin`. It passes the `plugin` object into `PresetStore` and `Widget`.

Build: `rojo build default.project.json -o RoRender.rbxm`, then copy the file into the local plugins folder. During development, `rojo serve` and the Rojo plugin are enough.

Install the add-on in Blender from the `blender/` folder, enable **ro-render**, and click **Start bridge** in the sidebar. Leave Blender open while rendering.

## Build order

1. Bridge health check, and a solid-color PNG written to a chosen folder.
2. Primitive parts, camera, and background color, shown in the widget preview.
3. Compositor: stroke, then drop shadow, inner shadow, outer glow, and inner glow, including background transparency.
4. MeshParts and textures, with the EditableMesh path and the asset-id fallback.
5. Save and load of the full configuration onto a second subject.
6. Cycles render to `{folder}/{subject}.png` at the requested size.

## How to know the first version works

Manual pass with Blender already running and the bridge started, in a place with two character models:

1. Select the first character. The viewport shows that character and nothing else. The Studio camera does not move.
2. Adjust rotation and position. Set FOV to 60, stroke thickness to 5, stroke color to `#000000`, size to 512×512, and an output folder.
3. Click **Preview**. The image has a black stroke about 5 pixels wide and the camera you framed. No file has been written yet.
4. Save the configuration as "Hero". Click **Fit**, then choose "Hero" in the dropdown. The fields return to the saved camera, stroke, FOV, and size.
5. Click **Render**. `{folder}/{CharacterName}.png` exists, is 512×512, and matches the preview. The status shows that path. Restart Studio, reopen the place, open the plugin. "Hero" is still in the dropdown and still loads.
6. Select the other character and click **Use selection**. The file name changes to that character. Load "Hero". Camera, stroke, FOV, and size match, and the file name is still the second character. Render writes a second PNG under that name in the same folder.
7. Quit Blender and click **Render**. The status says the bridge is not running, and no file changes.

## Later

- Wrap-cage deformation for layered clothing, so accessories hug the body the way Studio shows them.
- A lighting block on the configuration, if the fixed three-point rig is not enough.
- Batch render of every child model with the current configuration.
- Turntable frames.
