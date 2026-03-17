UBUNTU INSTALL (from the USB stick)
==================================

1) Plug in the USB on Ubuntu.
2) Open Terminal and cd into the USB folder that contains INSTALL_UBUNTU.sh
3) Run:

   bash ./INSTALL_UBUNTU.sh

4) After install finishes, run:

   bash ~/CITL-Factbook/RUN_FACTBOOK.sh

Notes:
- This installer copies the app from USB to ~/CITL-Factbook then installs dependencies + venv there.
- Ubuntu installs ffmpeg via apt; the Windows-only bin/ folder is not used.

What changed in the March 11, 2026 build
----------------------------------------
- The app is meant to be installed to your Ubuntu machine first, then run locally. This is faster and more reliable than running from the USB stick.
- Factbook answers are more controlled and safety-focused. If the system cannot confirm an answer from the local corpus, it now tells you that instead of guessing.
- A new App Sync utility is included so CITL can push updates between working copies and USB copies more cleanly.
- The document pipeline is more flexible and can handle more reference-style materials.

How staff should use this now
-----------------------------
1) For a first install on Ubuntu, run:

   bash ./INSTALL_UBUNTU.sh

2) For daily use after install, run the local copy:

   bash ~/CITL-Factbook/RUN_FACTBOOK.sh

3) Do not use the USB copy as the main working app. Use the USB to install or sync updates, then run the local copy in ~/CITL-Factbook.

4) When you need to move updates between CITL copies, run the sync utility:

   bash ~/CITL-Factbook/RUN_APP_SYNC.sh

   or from the USB root:

   bash ./RUN_APP_SYNC_UBUNTU.sh

What users should expect
------------------------
- Faster startup and fewer USB-related problems.
- Better factbook answers for direct reference questions like population, borders, languages, and comparisons.
- Clearer failure behavior. If the system cannot verify the answer from the offline source, it should say so plainly.
- Easier update flow for CITL staff managing multiple copies of the app.

Important caution
-----------------
- Re-running INSTALL_UBUNTU.sh replaces the contents of ~/CITL-Factbook with the USB copy. Treat it as a reinstall/update step, not an in-place merge.
- The sync utility is the safer option when you want to patch another copy without doing a full reinstall.

Plain-language release note
---------------------------
- See docs/CITL_FACTBOOK_UBUNTU_PLAIN_LANGUAGE_RELEASE_NOTE_2026-03-11.txt
