"""
Générateur de la fiche Word (DOCX) officielle pour le professeur / jury.
EduCloud SaaS — Guide d'Évaluation, Liens d'Accès et Comptes de Démonstration.
"""

from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from pathlib import Path
import datetime

def set_cell_background(cell, hex_color):
    """Applique une couleur d'arrière-plan hexadécimale à une cellule de tableau Word."""
    tcPr = cell._element.get_or_add_tcPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear')
    shd.set(qn('w:color'), 'auto')
    shd.set(qn('w:fill'), hex_color)
    tcPr.append(shd)

def set_cell_margins(cell, top=120, bottom=120, left=180, right=180):
    """Définit les marges internes d'une cellule en dxa (1 pt = 20 dxa)."""
    tcPr = cell._element.get_or_add_tcPr()
    tcMar = OxmlElement('w:tcMar')
    for m, val in [('w:top', top), ('w:bottom', bottom), ('w:left', left), ('w:right', right)]:
        node = OxmlElement(m)
        node.set(qn('w:w'), str(val))
        node.set(qn('w:type'), 'dxa')
        tcMar.append(node)
    tcPr.append(tcMar)

def create_guide_docx():
    doc = Document()

    # Configuration des marges de la page (2 cm partout)
    for section in doc.sections:
        section.top_margin = Inches(0.8)
        section.bottom_margin = Inches(0.8)
        section.left_margin = Inches(0.8)
        section.right_margin = Inches(0.8)

    # Palette de couleurs
    c_blue_dark = RGBColor(15, 28, 63)     # #0F1C3F
    c_blue_primary = RGBColor(29, 78, 216) # #1D4ED8
    c_teal = RGBColor(13, 148, 136)        # #0D9488
    c_gray = RGBColor(71, 85, 105)         # #475569
    c_gold = RGBColor(217, 119, 6)         # #D97706

    # ==================== BANDEAU D'EN-TÊTE ====================
    title_p = doc.add_paragraph()
    title_p.paragraph_format.space_before = Pt(0)
    title_p.paragraph_format.space_after = Pt(2)
    title_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r_kicker = title_p.add_run("RÉPUBLIQUE TUNISIENNE · PROJET DE FIN D'ÉTUDES / APPLICATION SAAS\n")
    r_kicker.font.size = Pt(9)
    r_kicker.font.bold = True
    r_kicker.font.color.rgb = c_teal

    r_title = title_p.add_run("EDUCLOUD SAAS — ESPACE ÉCOLE")
    r_title.font.name = "Calibri"
    r_title.font.size = Pt(24)
    r_title.font.bold = True
    r_title.font.color.rgb = c_blue_dark

    sub_p = doc.add_paragraph()
    sub_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sub_p.paragraph_format.space_after = Pt(16)
    r_sub = sub_p.add_run("Plateforme Intégrée de Gestion Scolaire Primaire & Centre Décisionnel BI\nGuide d'Évaluation & Identifiants Officiels de Connexion")
    r_sub.font.size = Pt(11)
    r_sub.font.color.rgb = c_gray

    # ==================== CADRE 1 : LIENS D'ACCÈS À L'APPLICATION ====================
    h1 = doc.add_paragraph()
    h1.paragraph_format.space_before = Pt(14)
    h1.paragraph_format.space_after = Pt(6)
    r_h1 = h1.add_run("1. Liens d'Accès Officiels à l'Application")
    r_h1.font.size = Pt(14)
    r_h1.font.bold = True
    r_h1.font.color.rgb = c_blue_primary

    table_url = doc.add_table(rows=2, cols=2)
    table_url.alignment = WD_TABLE_ALIGNMENT.CENTER
    table_url.autofit = False

    # Ligne 1 : Déploiement Cloud permanent
    cell_u1_l = table_url.cell(0, 0)
    cell_u1_r = table_url.cell(0, 1)
    cell_u1_l.width = Inches(2.2)
    cell_u1_r.width = Inches(4.8)
    set_cell_background(cell_u1_l, "EEF2FF")
    set_cell_background(cell_u1_r, "F8FAFC")
    set_cell_margins(cell_u1_l)
    set_cell_margins(cell_u1_r)

    p = cell_u1_l.paragraphs[0]
    p.add_run("🌐 Déploiement Cloud\n(Disponible 24h/24)").font.bold = True
    p.runs[0].font.size = Pt(9.5)
    p.runs[0].font.color.rgb = c_blue_primary

    p2 = cell_u1_r.paragraphs[0]
    run_link = p2.add_run("https://educloud-saas.onrender.com/login\n")
    run_link.font.bold = True
    run_link.font.size = Pt(10.5)
    run_link.font.color.rgb = c_blue_primary
    p2.add_run("Accessible depuis tout navigateur Google Chrome, Edge, Safari, smartphone ou tablette.").font.size = Pt(8.5)

    # Ligne 2 : Dépôt de Code Source GitHub
    cell_u2_l = table_url.cell(1, 0)
    cell_u2_r = table_url.cell(1, 1)
    cell_u2_l.width = Inches(2.2)
    cell_u2_r.width = Inches(4.8)
    set_cell_background(cell_u2_l, "F1F5F9")
    set_cell_background(cell_u2_r, "FFFFFF")
    set_cell_margins(cell_u2_l)
    set_cell_margins(cell_u2_r)

    p = cell_u2_l.paragraphs[0]
    p.add_run("💻 Code Source GitHub\n(Version validée)").font.bold = True
    p.runs[0].font.size = Pt(9.5)
    p.runs[0].font.color.rgb = c_gray

    p2 = cell_u2_r.paragraphs[0]
    r_git = p2.add_run("https://github.com/Famorycollab/educloud-saas\n")
    r_git.font.bold = True
    r_git.font.size = Pt(10)
    r_git.font.color.rgb = c_gray
    p2.add_run("Historique des commits, architecture SaaS, tests automatisés (34/34 OK).").font.size = Pt(8.5)

    # ==================== CADRE 2 : COMPTES DE CONNEXION ====================
    h2 = doc.add_paragraph()
    h2.paragraph_format.space_before = Pt(16)
    h2.paragraph_format.space_after = Pt(6)
    r_h2 = h2.add_run("2. Comptes de Démonstration & Mots de Passe par Profil")
    r_h2.font.size = Pt(14)
    r_h2.font.bold = True
    r_h2.font.color.rgb = c_blue_primary

    intro_users = doc.add_paragraph()
    intro_users.paragraph_format.space_after = Pt(6)
    intro_users.add_run("Sur la page de connexion, vous pouvez soit saisir les identifiants ci-dessous, soit cliquer directement sur les boutons de pré-remplissage rapide en bas du formulaire :").font.size = Pt(9.5)

    table_users = doc.add_table(rows=7, cols=5)
    table_users.alignment = WD_TABLE_ALIGNMENT.CENTER
    table_users.autofit = False

    headers = ["Profil / Rôle", "Nom d'utilisateur", "Mot de passe", "Nom affiché", "Périmètre d'Action Clé"]
    col_widths = [Inches(1.4), Inches(1.3), Inches(1.1), Inches(1.4), Inches(1.8)]

    # En-têtes
    hdr_cells = table_users.rows[0].cells
    for i, title in enumerate(headers):
        hdr_cells[i].width = col_widths[i]
        set_cell_background(hdr_cells[i], "1E40AF") # Bleu marine
        set_cell_margins(hdr_cells[i], top=140, bottom=140)
        p = hdr_cells[i].paragraphs[0]
        r = p.add_run(title)
        r.font.bold = True
        r.font.size = Pt(9)
        r.font.color.rgb = RGBColor(255, 255, 255)

    users_data = [
        ("Administrateur Général", "admin", "admin123", "Dr. Moncef Ben Salem", "Pilotage global, élèves, classes, centre décisionnel 10 dashboards, gestion complète."),
        ("Directeur d'Établissement", "directeur", "directeur123", "Dr. Moncef Ben Salem", "Surveillance pédagogique, validation bulletins, emploi du temps, stratégie N+1."),
        ("Responsable Comptable", "comptable", "compta123", "Sihem Mansouri", "Encaissements, références automatiques REC-2026-XXXX, export CSV, rappels impayés."),
        ("Secrétariat & Inscriptions", "secretaire", "secret123", "Meriem Trabelsi", "Pré-inscriptions, dossiers élèves, gestion des absences, certificats de scolarité."),
        ("Enseignant (Professeur)", "enseignant", "prof123", "Tarek Bouazizi", "Saisie des notes, devoirs, cahier de texte, emploi du temps de la classe."),
        ("Parent d'Élève", "parent", "parent123", "Karim Ben Amor", "Suivi des notes de l'enfant, téléchargement bulletin PDF, solde des frais & reçus."),
    ]

    for row_idx, data in enumerate(users_data, start=1):
        row_cells = table_users.rows[row_idx].cells
        bg_col = "FFFFFF" if row_idx % 2 == 1 else "F8FAFC"
        for col_idx, text in enumerate(data):
            row_cells[col_idx].width = col_widths[col_idx]
            set_cell_background(row_cells[col_idx], bg_col)
            set_cell_margins(row_cells[col_idx], top=100, bottom=100)
            p = row_cells[col_idx].paragraphs[0]
            r = p.add_run(text)
            r.font.size = Pt(8.5)
            if col_idx in (1, 2):
                r.font.bold = True
                r.font.name = "Consolas"
                if col_idx == 2:
                    r.font.color.rgb = c_gold
            elif col_idx == 0:
                r.font.bold = True

    # ==================== CADRE 3 : SCÉNARIOS DE NAVIGATION CONSEILLÉS ====================
    h3 = doc.add_paragraph()
    h3.paragraph_format.space_before = Pt(16)
    h3.paragraph_format.space_after = Pt(6)
    r_h3 = h3.add_run("3. Parcours de Démonstration Recommandé pour l'Évaluation")
    r_h3.font.size = Pt(14)
    r_h3.font.bold = True
    r_h3.font.color.rgb = c_blue_primary

    scenarios = [
        ("Étape 1 : Connexion & Découverte", "Connectez-vous avec admin / admin123. Admirez le tableau de bord avec bannière Aurora animée, les statistiques en temps réel et les accès rapides."),
        ("Étape 2 : Centre Décisionnel BI (10 Dashboards)", "Cliquez sur 'Centre Décisionnel BI' dans la barre latérale. Parcourez les 10 tableaux (Capacités, Finances, Pédagogie, Alertes Décrochage EWS, Simulateur IA N+1). Testez le bouton 'Imprimer Rapport BI'."),
        ("Étape 3 : Module Financier & Référence Automatique", "Dans le menu 'Paiements', observez le champ Référence pré-rempli automatiquement au format séquentiel 'REC-2026-XXXX'. Enregistrez un paiement et téléchargez le reçu officiel en PDF."),
        ("Étape 4 : Pédagogie, Bulletins & Dossier Élève", "Allez dans 'Élèves', ouvrez la fiche d'un élève (photo, allergies, historique). Dans 'Notes & Bulletins', générez le bulletin scolaire officiel avec moyenne pondérée."),
        ("Étape 5 : Test du Contrôle d'Accès Sécurisé", "Déconnectez-vous et connectez-vous avec le compte parent / parent123. Vérifiez qu'il ne voit que ses propres enfants et que le centre décisionnel confidentiel lui est strictement interdit (403 Forbidden)."),
    ]

    for title, desc in scenarios:
        sp = doc.add_paragraph()
        sp.paragraph_format.space_before = Pt(3)
        sp.paragraph_format.space_after = Pt(3)
        rt = sp.add_run(f"• {title} : ")
        rt.font.bold = True
        rt.font.size = Pt(9.5)
        rt.font.color.rgb = c_blue_dark
        rd = sp.add_run(desc)
        rd.font.size = Pt(9.5)
        rd.font.color.rgb = c_gray

    # ==================== CADRE 4 : EMAIL MODÈLE PRÊT À ENVOYER ====================
    h4 = doc.add_paragraph()
    h4.paragraph_format.space_before = Pt(16)
    h4.paragraph_format.space_after = Pt(6)
    r_h4 = h4.add_run("4. Modèle d'Email Prêt à l'Envoi pour la Professeure")
    r_h4.font.size = Pt(14)
    r_h4.font.bold = True
    r_h4.font.color.rgb = c_blue_primary

    email_box = doc.add_table(rows=1, cols=1)
    email_box.alignment = WD_TABLE_ALIGNMENT.CENTER
    c_email = email_box.cell(0, 0)
    c_email.width = Inches(7.0)
    set_cell_background(c_email, "F8FAFC")
    set_cell_margins(c_email, top=140, bottom=140, left=200, right=200)

    ep = c_email.paragraphs[0]
    ep.paragraph_format.line_spacing = 1.15
    email_text = """Objet : Présentation & Accès au Projet EduCloud SaaS — Application de Gestion Scolaire

Madame la Professeure,

J'ai le plaisir de vous transmettre les accès et la documentation officielle de notre projet de fin d'études « EduCloud SaaS — Espace École », une application Web moderne de gestion scolaire primaire intégrant un Centre Décisionnel Business Intelligence (10 dashboards analytiques).

1. Lien d'accès direct en ligne (accessible 24h/24) :
👉 https://educloud-saas.onrender.com/login

2. Code source & Versioning GitHub :
👉 https://github.com/Famorycollab/educloud-saas

3. Identifiants de connexion recommandés pour votre évaluation :
• Administrateur Général (accès complet & décisionnel) : admin / admin123
• Directeur d'établissement (pilotage & rentrée N+1)    : directeur / directeur123
• Responsable Comptable (finances & reçus REC-2026-XXXX) : comptable / compta123
• Enseignant (saisie des notes, devoirs, calendrier)    : enseignant / prof123
• Parent d'élève (suivi des notes & bulletins PDF)      : parent / parent123

Vous trouverez également en pièce jointe le document Word récapitulatif contenant le guide détaillé de navigation étape par étape ainsi que la matrice de contrôle d'accès.

Restant à votre entière disposition pour toute question ou démonstration complémentaire.

Bien respectueusement,
Famory Touré — Développeur du Projet EduCloud SaaS"""
    r_em = ep.add_run(email_text)
    r_em.font.size = Pt(9)
    r_em.font.color.rgb = c_blue_dark

    # Enregistrement du fichier
    output_path = Path("Guide_Evaluation_EduCloud_Professeur.docx")
    doc.save(str(output_path))
    print(f"SUCCESS: Document Word généré avec succès -> {output_path.resolve()}")

if __name__ == "__main__":
    create_guide_docx()
