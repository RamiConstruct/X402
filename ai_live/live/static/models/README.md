# Modèles exécutés sur le téléphone

| Fichier | Rôle | Source | Licence |
|---|---|---|---|
| `selfie_segmenter.tflite` (float16, 250 Ko) | Découpe de la silhouette (personne / fond) pour la prédiction du mouvement | [MediaPipe Image Segmenter](https://ai.google.dev/edge/mediapipe/solutions/vision/image_segmenter) | Apache 2.0 |

Bibliothèque d'exécution : `@mediapipe/tasks-vision@1.1.1` (Apache 2.0), chargée depuis cdn.jsdelivr.net.
Les images de la caméra sont traitées sur l'appareil et ne sont jamais envoyées.
