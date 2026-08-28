# OpenBao recovery ceremony

Run `recovery-ceremony-wizard.sh` from Windows Git Bash only when Stage 170 has
finished with OpenBao uninitialized and sealed. The wizard handles only the steps that
require the operator's Windows GPG key, clipboard, and cloud drive.

It exports only a public key, verifies the ciphertext recovery archive, decrypts one
selected share or root token directly into the Windows clipboard, and clears the
clipboard after the server ceremony. It never writes plaintext recovery material to
the repository, `.env`, GitHub, stdout, or a command argument.

Do not run the wizard in CI. Do not upload the private key or passphrase with the
ciphertext bundle. Re-running never overwrites a different public-key export or recovery
bundle.
