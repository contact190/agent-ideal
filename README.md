# Agent Idéal

**Un assistant Claude qui travaille sur ton ordinateur et ton compte Google, et qui sait aussi travailler seul à heures fixes.**

Tu lui écris ce que tu veux en français, en arabe ou en darija. Il le fait : fichiers, Excel, Word, PDF, Gmail, Google Drive/Sheets/Docs, Agenda, et n'importe quel logiciel grâce au contrôle de l'écran. Tu peux aussi lui confier des tâches qu'il refait chaque jour tout seul, comme relancer les fournisseurs, vérifier les commandes ou envoyer un rapport.

---

## ⬇️ Installation (Windows 10 / 11) — 5 minutes

### 1. Télécharger

👉 **[Télécharger l'Agent Idéal](https://github.com/contact190/agent-ideal/archive/refs/heads/main.zip)**

### 2. Extraire

Ouvre ton dossier **Téléchargements** et fais un **clic droit** sur `agent-ideal-main.zip`. Choisis **Extraire tout…**, puis choisis le dossier **Documents** et clique sur **Extraire**.

> ⚠️ Ne lance rien depuis l'intérieur du zip, sinon l'installation échoue.

### 3. Installer

Ouvre le dossier extrait `agent-ideal-main` (parfois il y en a un second à l'intérieur : ouvre-le aussi) jusqu'à voir **`1_INSTALLER.bat`**, et double-clique dessus.

- Si Windows affiche « Windows a protégé votre ordinateur », clique sur **Informations complémentaires**, puis **Exécuter quand même**.
- Si Python n'est pas installé, il est installé automatiquement.
- Attends le message **« Terminé ! »**. Ça prend de 2 à 5 minutes.

Un raccourci **Agent Idéal** apparaît sur le Bureau. L'agent démarrera aussi tout seul avec Windows, pour que les tâches automatiques tournent.

### 4. Premier lancement

Double-clique sur **Agent Idéal** (sur le Bureau). La page de l'agent s'ouvre dans ton navigateur.

1. **Clé API Claude**
   - Va sur **[console.anthropic.com](https://console.anthropic.com)** et crée un compte.
   - Dans **Billing**, ajoute du crédit (5 $ suffisent pour commencer).
   - Dans **API Keys**, crée une clé et copie-la.
   - Colle-la dans l'agent et clique sur **Enregistrer**.
2. **Compte Google** : clique sur **Connecter Google**, choisis ton compte et accepte.

C'est prêt : écris ta première demande en bas de l'écran. ✅

---

## 💬 Exemples de demandes

- « Fais un devis Excel pour 4 fenêtres 120×100 à 38 000 DA avec TVA 19 % et envoie-le en PDF à client@mail.com »
- « Range les fichiers de mon Bureau par type »
- « Résume mes e-mails non lus et dis-moi lesquels sont urgents »
- « Mets un rendez-vous jeudi 10 h chez M. Benali pour la prise de cotes »
- « Ouvre mon logiciel de stock et dis-moi ce qui est en rupture »

## 🕗 Tâches automatiques

Demande-les simplement dans la discussion :

- « **Chaque matin à 8 h**, lis la liste des fournisseurs dans le Google Sheet *Fournisseurs* et envoie à chacun la commande du jour. »
- « **Du samedi au jeudi à 17 h**, vérifie l'avancement des poses dans *Suivi chantiers* et envoie-moi un rapport par e-mail. »

L'agent te montre la tâche et te demande de la valider. Tu choisis alors à qui il a le droit d'écrire sans te demander. Tout le reste attendra ta validation. Pour voir tes tâches, leur historique, ou les mettre en pause, clique sur le bouton **🕗 Tâches**.

> Les tâches s'exécutent quand l'ordinateur est **allumé**. S'il était éteint à l'heure prévue, la tâche est rattrapée dans les 12 heures qui suivent.

## 📱 Sur ton téléphone (Telegram)

Tu peux suivre l'agent, valider ses actions et lui donner des ordres depuis ton téléphone, même loin du bureau.

1. Sur le téléphone, ouvre **Telegram** et cherche **@BotFather**.
2. Envoie **/newbot**, puis donne un nom (par exemple *Agent Idéal*) et un identifiant qui finit par *bot*.
3. BotFather te donne un **jeton**. Colle-le dans l'agent, dans **⚙ Réglages → Téléphone**.
4. **Scanne le QR code** affiché avec le téléphone, puis appuie sur **Démarrer**. C'est relié.

Ensuite, sur Telegram :
- **Écris ta demande ou envoie un message vocal** en français, en arabe ou en darija. L'agent te montre ce qu'il a compris, le fait sur le PC, puis te répond.
- Les **boutons en bas de Telegram** (Écran, Tâches, État, Stop, Nouvelle, Aide) servent de commandes rapides.
- Quand l'agent veut envoyer un mail ou supprimer quelque chose, tu reçois les boutons **✅ Valider / ❌ Refuser**.
- À la fin de chaque tâche automatique, tu reçois son compte-rendu.
- Envoie une **photo ou un fichier** : il est rangé sur le PC, dans *Reçus Telegram*, et l'agent s'en sert.
- Commandes : **/ecran** (capture du PC), **/taches**, **/etat**, **/stop**, **/nouvelle**.

**Vocaux :** pour une transcription précise, darija compris, crée une **clé Groq gratuite** sur [console.groq.com/keys](https://console.groq.com/keys) (*Create API Key*, sans carte bancaire). Colle-la dans **⚙ Réglages → Téléphone → Messages vocaux**. Sans clé, la transcription se fait sur le PC : c'est plus lent, et un modèle d'environ 500 Mo est téléchargé la première fois.

> Le bot ne répond qu'au téléphone que tu as relié. Le PC doit être allumé.

## 🔒 Sécurité

- **Envoyer un e-mail, partager, supprimer, remplacer un fichier, exécuter une commande** : une fenêtre te demande de valider.
- L'agent ne touche qu'aux **dossiers autorisés**, que tu choisis dans ⚙ Réglages.
- « Supprimer » ne détruit rien : les fichiers vont dans une corbeille récupérable.
- **Arrêt d'urgence** : clique sur **■ Stop**, ou place la souris dans le **coin en haut à gauche** de l'écran.
- Ta clé est rangée dans le coffre-fort de Windows. L'interface n'est accessible que depuis ton ordinateur.

## 🔄 Mise à jour

Double-clique sur **`4_METTRE_A_JOUR.bat`** dans le dossier de l'agent. Tes réglages, ta clé et tes tâches sont conservés.

## 🆘 En cas de problème

| Problème | Solution |
|---|---|
| Rien ne s'ouvre au lancement | Lance **`3_DEPANNAGE.bat`** et envoie une capture de la fenêtre. |
| « Clé refusée » | La clé est mal copiée, ou il n'y a plus de crédit sur console.anthropic.com. |
| Google : « accès bloqué » ou « refusé » | Ton adresse doit être autorisée par l'éditeur de l'agent. Contacte-le. |
| L'agent clique à côté | Mets l'échelle d'affichage Windows à 100 % ou 125 %. |
| Il manque une bibliothèque | Relance **`1_INSTALLER.bat`**. |

## 💰 Coût

L'agent est gratuit. Tu paies seulement ce que tu consommes chez Anthropic, et tu le vois sur console.anthropic.com, rubrique *Usage*. Le compteur de tokens en bas de l'écran donne une idée de la consommation.

---

*Agent Idéal — édité par Idéal Aluminium.*
