# PrusaSlicer 3 Plugins

Each plugin has its own folder under `plugins/`. The folder is the complete bundle, with a `manifest.json`, Lua source and any assets it needs. The starter uses `project.plugin` API 1.0.0 and targets PrusaSlicer 3.0.0-alpha13 or later.

## Start a plugin

Copy the starter and replace its example identity with your own.

```sh
cp -R templates/project-plugin plugins/my-plugin
python3 scripts/validate-bundles.py
```

Set the bundle ID in `manifest.json`, for example `io.github.tbetton.my-plugin`, and give the Lua entry in `main.lua` its own ID under that prefix. Change the name, description and version in the manifest. Use the author ID shown in the Prusa Marketplace author console before releasing. The starter's selected licence is MIT. Set a licence that applies to the code and assets you ship.

In PrusaSlicer 3, use **Help → Show Configuration Folder** to find the profile in use. Link the bundle into that profile's `lua` directory. Replace `/path/to/config` with the folder PrusaSlicer opens.

```sh
mkdir -p "/path/to/config/lua"
ln -s "$PWD/plugins/my-plugin" "/path/to/config/lua/my-plugin"
```

Choose **Plugins → Rescan**, then **Plugins → Examples → Starter Block** on an empty project. The default inputs add a 20 × 20 × 1 mm block. Edit the Lua and rescan to pick up changes. PrusaSlicer's own `plugin init` command can also generate a bundle.

- [PrusaSlicer Lua API](https://plugin-marketplace.prusa3d.com/docs/lua-api)
- [Bundle format](https://plugin-marketplace.prusa3d.com/docs/bundle)
- [Lua editor setup](https://plugin-marketplace.prusa3d.com/docs/editor-setup)

## Send a sliced file to Print Queue

Use [the local upload bridge](scripts/send-to-print-queue.py) with the **Print Queue** extension on Prusa Connect Local. PrusaSlicer uploads the sliced file to the bridge. The bridge stores the file in Connect Local and adds it to the selected printer's queue. Print Queue uses its normal readiness checks to start the job.

1. Open **Settings → Extensions → Print Queue** in Connect Local and set `slicer_upload_folder`, which defaults to `print-queue`. Create a credential with the **Operate** scope and copy the printer ID from `GET /api/v1/devices`. The account needs access to Print Queue, permission to operate that printer, and read and write access to the selected storage.
2. Run the bridge with Python 3.9–3.12. For a bridge on the same computer as PrusaSlicer, leave it on its default loopback address. Replace the server URL and printer ID with your own.

   ```sh
   /usr/bin/python3 scripts/send-to-print-queue.py \
     --server https://connect.example.local \
     --printer YOUR_PRINTER_ID
   ```

   Use `--storage` to select a storage other than `local`. For a second printer, run another instance with its ID and a different `--port`. For a Print Queue release without the `slicer_upload_folder` setting, pass `--folder print-queue` to set the folder on the bridge.

   To run the bridge next to Connect Local on its server, pass `--listen SERVER_LAN_IP --tls-cert /path/to/bridge.crt --tls-key /path/to/bridge.key`. The certificate must cover the address entered in PrusaSlicer. Use `--server http://127.0.0.1:8090` if Connect Local runs on that port on the same server.

3. In PrusaSlicer 3, add a physical printer named **Print Queue** and associate it with the matching printer preset. Choose **OctoPrint** as the host type. Enter `https://SERVER_LAN_IP:17891` for a server deployment, or `http://127.0.0.1:17891` for a bridge on the same computer. If you use a private CA, select its public certificate in **HTTPS CA File**. Paste the Connect Local credential into the API key field and use **Test** to check access to the queue.
4. Select the **Print Queue** physical printer, slice the project, click the network-send button and choose **Upload**. PrusaSlicer reports success after Print Queue returns a job ID. Confirm readiness as usual when the printer is available and the plate is clear.

If upload succeeds but the queue request fails, PrusaSlicer shows the server-side file path. Check **Print Queue** first, then use **Storage → Add to the print queue** on that file if the job is missing.

## Gitea to GitHub

Gitea `main` is the source branch. After validation, Gitea syncs the plugin sources and Marketplace workflow to GitHub `dev`. The first sync creates `dev` from GitHub `main`. Review and merge `dev` into `main` on GitHub when the release is ready.

To connect the repositories, initialize `main` once on `tbetton/prusa-plugin` and add a GitHub deploy key with write access to that repository. Store its private half as the Gitea Actions secret `PRUSA_PLUGIN_GITHUB_SSH_KEY`. If the GitHub repository has a different name, set Gitea Actions variable `PRUSA_PLUGIN_GITHUB_REPO` to `owner/repository`.

## Publish to Prusa

In the Prusa author console, register the **public** part of the signing key and a **Trusted publishing** entry for each plugin ID. Use the GitHub repository, workflow file `release.yml` and environment `release`. In the GitHub `release` environment, store the **private** signing key as `PRUSA_SLICER_PLUGIN_MARKETPLACE_SIGNING_KEY`. The GitHub deploy key and Prusa signing key serve different purposes.

For each release

1. Update the plugin's version in `manifest.json`, validate the bundles, and merge the synced GitHub `dev` branch.
2. Create a GitHub release targeting `main` with a tag of the form `<folder>/v<version>`, for example `my-plugin/v0.1.0`. Use the GitHub release body for the notes. Mark it as a pre-release for the Prusa **beta** channel.
3. Publish the GitHub release. GitHub signs the selected folder and submits it to Prusa for review. Follow the run under **Actions → PrusaSlicer Plugin Marketplace**.

A push or pull request runs validation. A published GitHub release triggers the Marketplace submission. The starter in `templates/` is outside the release folder selection.

[PrusaSlicer Marketplace action and trusted publishing guide](https://github.com/prusa3d/plugin-marketplace-publish)
