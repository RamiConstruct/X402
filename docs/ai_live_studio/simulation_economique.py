"""Simulation économique AI LIVE / AI STUDIO — hypothèses explicites, aucune demande garantie.

Usage : python3 docs/ai_live_studio/simulation_economique.py
Toutes les valeurs sont des HYPOTHÈSES à remplacer par des mesures réelles.
Montants en USD/mois, arrondis à l'unité uniquement à l'affichage.
"""
from decimal import Decimal as D

# --- Hypothèses d'usage (par rapport aux inscrits) -------------------------
TAUX_ACTIFS = D("0.25")      # inscrits actifs dans le mois
TAUX_PAYANTS = D("0.05")     # inscrits payants (conversion freemium prudente)

# --- Revenus par payant ------------------------------------------------------
ABONNEMENT = D("19")         # plan Créateur
CREDITS_ACHETES = D("25")    # consommation moyenne au-delà des crédits inclus
CREDITS_INCLUS_COUT = D("6") # coût fournisseur des crédits inclus dans l'abonnement
MARGE_BRUTE_CREDITS = D("0.45")  # le coût fournisseur = 55 % du prix des crédits

# --- Coûts variables ----------------------------------------------------------
FRAIS_PAIEMENT = D("0.06")   # Merchant of Record / Stripe + taxes (~5-7 %)
COUT_ACTIF_GRATUIT = D("0.35")  # essais gratuits limités, stockage, STT, modération
STOCKAGE_PAR_PAYANT = D("1.20") # R2/S3 vidéos + proxies, rétention 30 jours

# --- Coûts fixes par palier (outillage IA dev, VPS, base, monitoring, juridique,
#     support/modération, salaires éventuels) ----------------------------------
FIXES = {10: D("450"), 100: D("650"), 1_000: D("1800"),
         10_000: D("9000"), 100_000: D("65000")}


def simuler(inscrits: int) -> dict:
    n = D(inscrits)
    actifs = n * TAUX_ACTIFS
    payants = n * TAUX_PAYANTS
    gratuits_actifs = actifs - payants
    revenu = payants * (ABONNEMENT + CREDITS_ACHETES)
    cout_fournisseurs = payants * (CREDITS_INCLUS_COUT + CREDITS_ACHETES * (1 - MARGE_BRUTE_CREDITS))
    cout_variable = (cout_fournisseurs + revenu * FRAIS_PAIEMENT
                     + gratuits_actifs * COUT_ACTIF_GRATUIT + payants * STOCKAGE_PAR_PAYANT)
    marge_brute = revenu - cout_variable
    fixes = FIXES[inscrits]
    return dict(inscrits=inscrits, actifs=actifs, payants=payants, revenu=revenu,
                cout_variable=cout_variable, marge_brute=marge_brute,
                taux_mb=(marge_brute / revenu) if revenu else D(0),
                fixes=fixes, resultat=marge_brute - fixes)


def seuil_gpu(prix_location_h, capex, duree_mois, fixes_mois, kw, prix_kwh, pue):
    """Heures/mois au-delà desquelles posséder coûte moins cher que louer."""
    amort = capex / duree_mois
    var_h = kw * pue * prix_kwh
    total_fixe = amort + fixes_mois
    heures = total_fixe / (prix_location_h - var_h)
    return amort, total_fixe, var_h, heures, heures / D(730)


if __name__ == "__main__":
    print("| Inscrits | Actifs | Payants | Revenu | Coûts variables | Marge brute | MB % | Coûts fixes | Résultat |")
    print("|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for n in FIXES:
        r = simuler(n)
        print(f"| {n:,} | {r['actifs']:,.0f} | {r['payants']:,.1f} | {r['revenu']:,.0f} | "
              f"{r['cout_variable']:,.0f} | {r['marge_brute']:,.0f} | {r['taux_mb']*100:.0f} % | "
              f"{r['fixes']:,.0f} | {r['resultat']:,.0f} |")
    print()
    cas = {
        "RTX 5090 (Sydney, colo)": (D("0.69"), D("5000"), D(36), D("90"), D("0.6"), D("0.22"), D("1.4")),
        "RTX 5090 (Algérie, hyp.)": (D("0.69"), D("5800"), D(36), D("120"), D("0.6"), D("0.05"), D("1.6")),
        "H100 80GB (colo)": (D("2.20"), D("33000"), D(48), D("260"), D("1.0"), D("0.20"), D("1.4")),
    }
    print("| Cas | Amortissement/mois | Fixe total/mois | Énergie USD/h | Seuil h/mois | Utilisation mini |")
    print("|---|---:|---:|---:|---:|---:|")
    for nom, a in cas.items():
        amort, tf, vh, h, u = seuil_gpu(*a)
        print(f"| {nom} | {amort:,.0f} | {tf:,.0f} | {vh:.3f} | {h:,.0f} | {u*100:.0f} % |")
