# Source de référence

`ov519.c` est une copie non modifiée du pilote **gspca** du noyau Linux :

    drivers/media/usb/gspca/ov519.c
    https://raw.githubusercontent.com/torvalds/linux/master/drivers/media/usb/gspca/ov519.c

Licence **GPL-2.0**. Auteurs listés en tête du fichier.

Ce fichier est la seule description publique complète du bridge OV519. Les
tables de registres, les séquences d'initialisation et le format de paquet
utilisés par `eyetoy/` en sont portés — ce qui fait de ce projet une œuvre
dérivée, également sous GPL-2.0.

La copie est conservée dans le dépôt pour que cette filiation soit vérifiable
et pour que le portage reste comparable à son original.

## Écarts assumés par rapport au pilote

- **VGA n'utilise pas les réglages 15 fps.** Le pilote associe 15 fps à un
  diviseur d'horloge capteur de 1. Le bus USB 1.1 plafonne déjà le VGA à
  ~13,8 fps, donc appliquer ce diviseur descend la cadence à ~6,7 fps.
  L'application demande 30 fps en VGA et laisse le bus faire la limite.
- **Pas de miroir matériel.** `sethvflip` ne vaut que pour les capteurs
  OV7660/OV7670 ; sur OV7648 le miroir est fait en logiciel.
- **Pas de contrôle de contraste.** Le pilote n'expose aucun registre de
  contraste pour l'OV7648.
