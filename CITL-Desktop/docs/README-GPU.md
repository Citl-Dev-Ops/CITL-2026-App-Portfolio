# Desktop LLM EZ Install Kits — GPU Tower Bootstrap

1) **Drivers**: sudo ubuntu-drivers autoinstall && sudo reboot
2) **Docker + NVIDIA Toolkit** (Ubuntu): install toolkit, 
vidia-ctk runtime configure, systemctl restart docker.
3) **Burn-in gate**: sudo bash gpu/burnin/burnin.sh → PASS = zero errors; temps < 90°C
4) **Ollama**: ash gpu/ollama/install_ollama.sh
5) **Model**: adjust Modelfile.sample; ash gpu/ollama/create_flexcoach.sh
6) Save logs in SharePoint: **CITL/FLEX-Coach/GPU/**
