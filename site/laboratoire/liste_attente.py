"""Exporte la liste d'attente de labotory.site en CSV (à ouvrir dans un tableur).

Usage : LABO_UPDATE_TOKEN=... python3 site/laboratoire/liste_attente.py > liste_attente.csv
Les adresses sont des données personnelles : ne pas publier le fichier ni le committer.
"""
import csv
import json
import os
import sys
import urllib.request

req = urllib.request.Request(
    "https://labotory.site/liste-attente.json",
    headers={"Authorization": f"Bearer {os.environ['LABO_UPDATE_TOKEN']}"},
)
data = json.load(urllib.request.urlopen(req, timeout=30))
w = csv.writer(sys.stdout)
w.writerow(["email", "profil", "interet", "inscrit_le", "pays"])
for i in data["inscrits"]:
    w.writerow([i["email"], i["profil"], i["interet"], i["inscrit_le"], i.get("pays") or ""])
print(f"{data['total']} inscrit(s)", file=sys.stderr)
