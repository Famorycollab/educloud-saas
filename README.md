# 🏫 EduCloud SaaS Pro — Plateforme de Gestion Scolaire Multi-Établissements & Business Intelligence

> **Projet pratique – Cloud et Big Data**  
> *Développement et déploiement d'une application SaaS de gestion scolaire intégrant un module Business Intelligence et Aide à la Décision.*  
> **Étudiant : TOURE**  
> **Année universitaire : 2026-2027**

---

## 🌐 Déploiement Cloud & Accès en Ligne

* **URL Publique Cloud (HTTPS) :** [https://ingredients-conclusions-unlike-retreat.trycloudflare.com](https://ingredients-conclusions-unlike-retreat.trycloudflare.com)
* **Accès Local :** [http://127.0.0.1:5000](http://127.0.0.1:5000)
* **Livrable Word officiel :** `Projet_Cloud_BigData_TOURE.docx` *(à la racine du projet)*

---

## 🏛️ Architecture Multi-Établissements (Multi-Tenant)

L'application gère plusieurs établissements scolaires de manière totalement cloisonnée et indépendante, avec bascule instantanée pour les profils de direction :

1. **Établissement N°1 : Groupe Scolaire International d'Excellence (Dakar, Sénégal)**  
   *Code : EXCELLENCE · Devise : FCFA · Primaire complet (CP à CM2)*
2. **Établissement N°2 : Institut Polyvalent Horizon Avenir (Abidjan, Côte d'Ivoire)**  
   *Code : HORIZON · Devise : FCFA · Collège (6ème à 3ème)*

---



---

## 📊 Module Business Intelligence & Aide à la Décision (SID)

L'application intègre un **Système d'Information Décisionnel** complet composé de **10 Tableaux de Bord** :

1. **Dashboard 1 – Vue Globale de l'Établissement** : Effectifs totaux, classes, taux d'occupation, alertes saturation (>95%) ou sous-remplissage (<60%), graphique d'évolution pluriannuelle.
2. **Dashboard 2 – Gestion Financière & Trésorerie** : Total attendu, montant encaissé, reste à recouvrer, taux de recouvrement, projection mensuelle de cashflow, relance 1-clic des impayés.
3. **Dashboard 3 – Performance Pédagogique** : Moyenne générale, taux de réussite/échec, moyennes par classe et matière, détection des élèves en difficulté.
4. **Dashboard 4 – Absences & Corrélations Big Data** : Volume d'absences, répartition justifiées vs injustifiées, élèves chroniques, analyse statistique démontrant l'impact des absences sur la moyenne.
5. **Dashboard 5 – RH & Enseignants** : Volume horaire hebdomadaire par enseignant, détection de surcharge (>20h) et disponibilité horaire pour suppléance.
6. **Dashboard 6 – Inscriptions & Rétention** : Taux de fidélisation (93.4%), flux de nouvelles inscriptions, répartition géographique par quartier des familles.
7. **Dashboard 7 – Communication Parents** : Taux de lecture des messages (92%), annonces ciblées, réactivité parentale.
8. **Dashboard 8 – Emplois du Temps & Salles** : Taux d'occupation des salles (base 30h/semaine), détection des salles sous-utilisées (<35%), 0 conflit d'horaires.
9. **Dashboard 9 – Early Warning System (EWS · Détection Précoce des Risques)** : Algorithme décisionnel croisant notes < 10, absences répétées et retards financiers pour déclencher une alerte et un plan d'intervention précoce.
10. **Dashboard 10 – Stratégique, Prévisions & Simulateur N+1** : Simulateur interactif de rentrée 2027-2028 calculant en temps réel les besoins en salles, enseignants et revenus prévisionnels avec recommandations décisionnelles de l'IA.

---

## 🧪 Tests Automatisés

La suite de tests vérifie l'ensemble des fonctionnalités critiques :

```bash
python -m unittest discover -s tests -v
```

*Résultat : 22/22 tests réussis (100% de succès).*
