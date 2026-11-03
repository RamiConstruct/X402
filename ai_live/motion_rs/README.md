# motion_rs — mesure du mouvement en Rust (WebAssembly)

Port fidèle de `blockFlow` (`live/static/rendu.js`) : flux de mouvement par blocs 8×8 sur une image 64×64,
recherche en deux niveaux. Sans dépendance, mémoire statique, 7–8 Ko.

| Mesure (même image, Chromium) | JavaScript | Rust / WebAssembly |
|---|---|---|
| Temps par image | ~3,5 ms | ~0,37 ms (×9) |
| Écart entre résultats | — | < 0,000001 pixel |

Sur téléphone (processeur 3 à 5 fois plus lent), ça libère environ 10 à 18 ms par image, sur un budget
de 33 ms à 30 i/s. Le rendu charge `motion.wasm` et garde la version JavaScript en secours.

```sh
rustup target add wasm32-unknown-unknown
cargo build --release --target wasm32-unknown-unknown
cp target/wasm32-unknown-unknown/release/motion_rs.wasm ../live/static/motion.wasm
node bench.mjs        # compare les deux versions (résultats et temps)
```
