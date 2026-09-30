# Installer l’impression sur Raspberry Pi

## 1 Copier le projet sur le Pi

Installer Raspberry Pi OS **64 bits**, connecter le Pi à Internet et brancher l’imprimante USB ou réseau. Décompresser ce ZIP.

Si les fichiers sont sur le Mac, copier le dossier depuis le terminal du Mac en remplaçant `UTILISATEUR_PI` et `IP_PI` :

```bash
scp -r ~/Downloads/bordereau-impression-raspberry UTILISATEUR_PI@IP_PI:~/
ssh UTILISATEUR_PI@IP_PI
```

## 2 Installer le service sur le Pi

Exécuter sur le **Raspberry Pi**, pas sur le Mac :

```bash
cd ~/bordereau-impression-raspberry
sudo bash install.sh
```

## 3 Configurer l’imprimante

Ajouter l’imprimante dans le gestionnaire d’imprimantes du Pi ou dans CUPS : ouvrir `http://localhost:631` depuis le Pi, puis **Administration → Add Printer**. Pour une imprimante réseau, utiliser son adresse et le protocole indiqué par le fabricant. Installer son pilote ARM si nécessaire.

Afficher le nom de l’imprimante :

```bash
lpstat -p -d
```

Ouvrir la configuration :

```bash
sudo nano /etc/bordereau/config.env
```

Renseigner `PRINTER_NAME` avec le nom CUPS, par exemple `PRINTER_NAME=Bureau`. Conserver `API_TOKEN` : c’est la clé qui sera utilisée dans n8n.

```bash
sudo systemctl restart bordereau
```

Copier un PDF de test sur le Pi et tester l’impression en remplaçant `Bureau` et le chemin :

```bash
sudo -u bordereau lp -d Bureau /chemin/vers/test.pdf
```

Vérifier que le papier sort correctement avant de continuer.

## 4 Donner accès au Pi depuis n8n

Si n8n est hébergé à distance, installer **ngrok pour Linux ARM64** depuis <https://ngrok.com/download>, puis exécuter sur le Pi :

```bash
read -rsp 'Jeton ngrok : ' NGROK_TOKEN
ngrok config add-authtoken "$NGROK_TOKEN"
unset NGROK_TOKEN
ngrok http 8000
```

Laisser cette commande fonctionner et noter l’adresse HTTPS affichée. Choisir une adresse stable dans ngrok si disponible ; sinon mettre à jour n8n lorsque l’adresse change. Après un redémarrage du Pi, relancer `ngrok http 8000`. Le service d’impression, lui, redémarre automatiquement.

## 5 Modifier uniquement le nœud d’impression dans n8n

**Conserver Render et les nœuds de génération du PDF.** Conserver aussi le téléchargement du PDF depuis Drive.

Ouvrir **Envoyer au Bridge d’Impression** et configurer :

| Champ | Valeur |
|---|---|
| Method | `POST` |
| URL | `https://VOTRE_ADRESSE_NGROK/print` |
| Send Body | Activé |
| Body Content Type | `n8n Binary File` ou `binaryData`, selon la version |
| Input Data Field Name | `data` |
| Send Headers | Activé |
| Content-Type | `application/pdf` |
| Idempotency-Key | Expression ci-dessous |
| Response Format | `JSON` |

Pour `Idempotency-Key`, utiliser :

```javascript
{{ 'drive-' + $('Enregistrer dans Drive').first().json.id }}
```

Créer un identifiant n8n **Header Auth** :

- **Name** : `X-API-Key`
- **Value** : la valeur de `API_TOKEN` dans `/etc/bordereau/config.env`

Sélectionner **Generic Credential Type → Header Auth**, puis cet identifiant sur le nœud d’impression. Ne pas mettre la clé dans le code ni dans GitHub.

Le parcours reste : **Render génère le PDF → Drive conserve le PDF → n8n envoie le PDF au Pi → le Pi imprime**.

## 6 Tester puis activer

Lancer manuellement le workflow avec des données de test. Vérifier que le PDF est généré sur Render, enregistré dans Drive, reçu par le Pi et imprimé correctement.

Une réponse HTTP **202** signifie que CUPS a accepté le travail ; vérifier aussi le papier. Un nouvel appel avec la même clé et le même PDF retourne **200** et `duplicate: true`, sans soumettre une nouvelle impression. Si un appel est incertain ou renvoie **409**, contrôler la file avant de relancer :

```bash
lpstat -o
sudo journalctl -u bordereau -n 50 --no-pager
```

Ne pas arrêter Render. Activer la planification existante seulement après un test complet. Dans le workflow initial, les notifications peuvent continuer indépendamment de l’impression : contrôler la sortie papier avant d’annoncer sa disponibilité.

En cas de panne du service :

```bash
sudo systemctl status bordereau --no-pager
sudo systemctl restart bordereau
```

Conserver `/var/lib/bordereau/jobs.sqlite3` : cette base évite les doubles soumissions. Les essais sur le Pi, l’imprimante et votre instance n8n restent à réaliser.
# bordereau-bridge-main
