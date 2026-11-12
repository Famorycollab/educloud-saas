import zipfile
import os
from datetime import datetime

DOCX_PATH = "Projet_Cloud_BigData_TOURE.docx"

content_types_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
</Types>"""

rels_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""

doc_rels_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""

styles_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:docDefaults>
    <w:rPrDefault>
      <w:rPr>
        <w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Calibri"/>
        <w:sz w:val="22"/>
        <w:szCs w:val="22"/>
        <w:lang w:val="fr-FR"/>
      </w:rPr>
    </w:rPrDefault>
  </w:docDefaults>
  <w:style w:type="paragraph" w:styleId="Title">
    <w:name w:val="Title"/>
    <w:rPr>
      <w:b/>
      <w:color w:val="1E3C72"/>
      <w:sz w:val="48"/>
    </w:rPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="Heading1">
    <w:name w:val="heading 1"/>
    <w:rPr>
      <w:b/>
      <w:color w:val="1E3C72"/>
      <w:sz w:val="32"/>
    </w:rPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="Heading2">
    <w:name w:val="heading 2"/>
    <w:rPr>
      <w:b/>
      <w:color w:val="2A5298"/>
      <w:sz w:val="26"/>
    </w:rPr>
  </w:style>
</w:styles>"""

def p(text, style=None, bold=False, italic=False, color=None, size=None, align=None):
    jc = f'<w:jc w:val="{align}"/>' if align else ""
    p_style = f'<w:pStyle w:val="{style}"/>' if style else ""
    r_bold = "<w:b/>" if bold else ""
    r_italic = "<w:i/>" if italic else ""
    r_color = f'<w:color w:val="{color}"/>' if color else ""
    r_size = f'<w:sz w:val="{size}"/>' if size else ""
    return f"""<w:p>
      <w:pPr>{p_style}{jc}</w:pPr>
      <w:r>
        <w:rPr>{r_bold}{r_italic}{r_color}{r_size}</w:rPr>
        <w:t xml:space="preserve">{text}</w:t>
      </w:r>
    </w:p>"""

def table_xml(headers, rows):
    xml = ['<w:tbl>',
           '<w:tblPr><w:tblW w:w="5000" w:type="pct"/><w:tblBorders><w:top w:val="single" w:sz="6" w:space="0" w:color="CCCCCC"/><w:bottom w:val="single" w:sz="6" w:space="0" w:color="CCCCCC"/><w:insideH w:val="single" w:sz="4" w:space="0" w:color="EEEEEE"/><w:insideV w:val="none"/></w:tblBorders></w:tblPr>']
    # Headers
    xml.append('<w:tr><w:trPr><w:tblHeader/></w:trPr>')
    for h in headers:
        xml.append(f'<w:tc><w:tcPr><w:shd w:val="clear" w:color="auto" w:fill="1E3C72"/></w:tcPr><w:p><w:pPr><w:jc w:val="center"/></w:pPr><w:r><w:rPr><w:b/><w:color w:val="FFFFFF"/></w:rPr><w:t>{h}</w:t></w:r></w:p></w:tc>')
    xml.append('</w:tr>')
    # Rows
    for r in rows:
        xml.append('<w:tr>')
        for c in r:
            xml.append(f'<w:tc><w:tcPr><w:tcMar><w:top w:w="120" w:type="dxa"/><w:bottom w:w="120" w:type="dxa"/></w:tcMar></w:tcPr><w:p><w:r><w:t>{c}</w:t></w:r></w:p></w:tc>')
        xml.append('</w:tr>')
    xml.append('</w:tbl>')
    return "".join(xml)

def generate_document(cloud_url="https://saas-ecole-bi.trycloudflare.com"):
    body = []
    
    # Title & Metadata
    body.append(p("PROJET PRATIQUE – CLOUD ET BIG DATA", style="Title", align="center"))
    body.append(p("Développement et déploiement d'une application SaaS de gestion scolaire avec Business Intelligence et Aide à la Décision", align="center", italic=True, size="24", color="555555"))
    body.append(p("Étudiant : TOURE", bold=True, size="26", align="center", color="1E3C72"))
    body.append(p(f"Date de remise : Novembre 2026 · Année Universitaire 2026-2027", align="center", color="777777"))
    body.append(p(""))
    
    # Section 1 : Informations d'accès
    body.append(p("1. Informations de Connexion & Accès en Ligne", style="Heading1"))
    body.append(p("L'application a été déployée sur une infrastructure Cloud moderne et est accessible en ligne à l'adresse suivante :"))
    body.append(p(f"🌐 Lien d'accès Cloud : {cloud_url}", bold=True, size="26", color="0D6EFD"))
    body.append(p("🔗 Accès local de secours : http://127.0.0.1:5000", italic=True, color="666666"))
    body.append(p(""))

    # Section 2 : Établissement 1
    body.append(p("2. Établissement de Démonstration N°1 : Groupe Scolaire d'Excellence (Dakar)", style="Heading1"))
    body.append(p("Établissement d'enseignement primaire complet (CP à CM2) avec suivi financier et pédagogique."))
    
    headers1 = ["Rôle Utilisateur", "Identifiant", "Mot de passe", "Périmètre & Droits d'Accès"]
    rows1 = [
        ["Directeur Général", "directeur", "directeur123", "Accès complet aux 10 Dashboards BI, simulateur N+1 et alertes."],
        ["Administrateur", "admin", "admin123", "Gestion des élèves, classes, affectations, audit log et sécurité."],
        ["Comptable", "comptable", "compta123", "Gestion des paiements, reçus PDF, relances automatiques d'impayés."],
        ["Secrétaire", "secretaire", "secret123", "Pré-inscriptions, dossiers scolaires et scolarité."],
        ["Enseignant", "enseignant", "prof123", "Saisie des notes, devoirs, justifications d'absences."],
        ["Parent d'élève", "parent", "parent123", "Consultation des bulletins, suivi d'absences, paiement."],
        ["Élève", "eleve", "eleve123", "Consultation des devoirs, notes et emploi du temps personnel."],
    ]
    body.append(table_xml(headers1, rows1))
    body.append(p(""))

    # Section 3 : Établissement 2
    body.append(p("3. Établissement de Démonstration N°2 : Institut Polyvalent Horizon (Abidjan)", style="Heading1"))
    body.append(p("Établissement secondaire indépendant permettant de démontrer le cloisonnement strict Multi-Tenant."))
    
    rows2 = [
        ["Directeur Général", "directeur_horizon", "directeur123", "Tableaux de bord BI dédiés à l'établissement d'Abidjan."],
        ["Administrateur", "admin_horizon", "admin123", "Configuration et gestion locale de l'établissement."],
        ["Comptable", "comptable_horizon", "compta123", "Facturation, gestion de trésorerie locale (FCFA)."],
        ["Enseignant", "enseignant_horizon", "prof123", "Classes de 6ème et 3ème, évaluations et cours."],
        ["Parent d'élève", "parent_horizon", "parent123", "Suivi scolaire des enfants inscrits à Abidjan."],
        ["Élève", "eleve_horizon", "eleve123", "Accès personnel aux notes et devoirs."],
    ]
    body.append(table_xml(headers1, rows2))
    body.append(p(""))

    # Section 4 : SuperAdmin
    body.append(p("4. Profil Plateforme SaaS : SuperAdmin Multi-Établissements", style="Heading1"))
    rows_super = [
        ["SuperAdmin Global", "superadmin", "superadmin123", "Supervision globale, bascule instantanée entre écoles."],
    ]
    body.append(table_xml(headers1, rows_super))
    body.append(p(""))

    # Section 5 : Les 10 Dashboards BI
    body.append(p("5. Module Business Intelligence & Aide à la Décision (10 Tableaux de Bord)", style="Heading1"))
    body.append(p("L'application intègre un véritable Système d'Information Décisionnel (SID) accessible depuis l'onglet 'Centre Décisionnel BI' :"))
    
    dashboards = [
        ("Dashboard 1 - Vue Globale & Capacité", "Effectifs totaux, taux d'occupation des classes, détection des saturations (>95%) et sous-charges."),
        ("Dashboard 2 - Gestion Financière & Trésorerie", "Total frais attendus, encaissés, reste à recouvrer, taux de recouvrement, projection mensuelle de trésorerie."),
        ("Dashboard 3 - Performance Pédagogique", "Moyennes par classe et par matière, taux de réussite, classement des matières, détection des élèves en difficulté."),
        ("Dashboard 4 - Absences & Corrélations Big Data", "Analyse croisée démontrant statistiquement la corrélation directe entre absentéisme répété et chute des résultats."),
        ("Dashboard 5 - RH & Charge Enseignante", "Volume horaire hebdomadaire par enseignant, détection de surcharge (>20h) et disponibilité pour suppléance."),
        ("Dashboard 6 - Inscriptions & Fidélisation", "Taux de rétention (93.4%), nouvelles inscriptions, répartition par zone géographique des familles."),
        ("Dashboard 7 - Communication Parents", "Taux d'ouverture et de lecture des messages (92%), réactivité et annonces ciblées."),
        ("Dashboard 8 - Salles & Emplois du Temps", "Taux d'utilisation de chaque salle (base 30h), détection des salles sous-utilisées (<35%)."),
        ("Dashboard 9 - Early Warning System (EWS)", "Algorithme d'alerte précoce croisant notes < 10/20, absences injustifiées et retards financiers pour déclencher un plan d'intervention."),
        ("Dashboard 10 - Stratégique & Simulateur N+1", "Simulateur dynamique pour la rentrée 2027-2028 calculant en temps réel les besoins en salles, enseignants et prévisions budgétaires."),
    ]
    for d_title, d_desc in dashboards:
        body.append(p(f"• {d_title} :", bold=True, color="1E3C72"))
        body.append(p(f"  {d_desc}"))

    body_xml = "".join(body)
    document_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    {body_xml}
    <w:sectPr>
      <w:pgSz w:w="11906" w:h="16838"/>
      <w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/>
    </w:sectPr>
  </w:body>
</w:document>"""

    with zipfile.ZipFile(DOCX_PATH, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types_xml)
        z.writestr("_rels/.rels", rels_xml)
        z.writestr("word/_rels/document.xml.rels", doc_rels_xml)
        z.writestr("word/styles.xml", styles_xml)
        z.writestr("word/document.xml", document_xml)

    print(f"Document generated successfully at {DOCX_PATH}!")

if __name__ == "__main__":
    generate_document()
