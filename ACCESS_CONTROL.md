# Contrôle d'accès

Les rôles sont rechargés depuis la base et validés côté serveur par `login_required`; les sessions des comptes désactivés sont révoquées. Masquer un lien dans l'interface n'est jamais considéré comme une autorisation. Chaque formulaire POST est aussi soumis au contrôle CSRF. L'administrateur ne peut pas désactiver son propre compte ni le dernier compte administrateur actif.

| Fonction | Administrateur | Enseignant | Parent | Élève | Comptable | Secrétariat |
| --- | --- | --- | --- | --- | --- | --- |
| Comptes et affectations | Gestion | — | — | — | — | — |
| Élèves | Gestion complète | Classes affectées | Enfants associés | Dossier associé | Consultation nécessaire aux paiements | Inscriptions et dossiers |
| Classes et matières | Gestion | Consultation selon affectations | — | — | — | — |
| Notes et bulletins | Gestion | Classes/matières affectées | Enfants associés | Dossier associé | — | — |
| Emploi du temps | Gestion | Enseignant connecté | Classes des enfants | Sa classe | — | — |
| Absences | Gestion | Classes affectées | Consultation et justification des enfants | Consultation de son dossier | — | — |
| Paiements et tarifs | Gestion | — | Paiements/reçus des enfants | — | Gestion financière | — |
| Devoirs | Gestion | Devoirs affectés | Classes des enfants | Dépôt de son travail | — | — |
| Messages/annonces | Administration | Relations pédagogiques affectées | École et enseignants de l'enfant | École et enseignants de sa classe | Parents liés et administration | École et parents |

## Règles métier contrôlées côté serveur

- Les dossiers parent/élève ne sont accessibles qu'aux comptes explicitement associés.
- Un enseignant doit avoir une affectation enseignant-classe-matière avant de saisir une note, publier un devoir ou une correction.
- Les capacités des classes sont contrôlées lors de l'inscription et de l'affectation d'un élève.
- Les chevauchements de créneaux de classe, enseignant et salle sont refusés.
- Les notes sont bornées par le barème de l'évaluation et l'élève doit appartenir à la classe de l'évaluation.
- Les dépôts sont refusés après la date limite; les corrections ne sont téléchargeables qu'après la date de remise.
- Les reçus et bulletins PDF vérifient que le parent ou l'élève est lié au dossier demandé.
- Les fichiers téléversés sont limités par taille et extension et ne sont servis qu'après vérification du rôle et du lien avec la classe.
- Les suppressions des élèves sont logiques; les classes/matières liées à des données historiques ne peuvent pas être supprimées physiquement.
- Un compte élève ne peut être lié qu'à un seul dossier; les comptes parents peuvent être liés à plusieurs enfants.
- Les opérations d'inscription vérifient la capacité et l'année scolaire de la classe.

Cette matrice décrit les objectifs d'autorisation; les permissions doivent rester accompagnées de tests d'intégration et être revues lors de l'ajout de chaque nouvelle route.
