Write-Host "Opening ShipVoice SSH tunnel..."
Write-Host "Local ports:"
Write-Host "  ASR  127.0.0.1:18001 -> remote 127.0.0.1:8001"
Write-Host "  TTS  127.0.0.1:18002 -> remote 127.0.0.1:8002"
Write-Host "  LLM  127.0.0.1:18034 -> remote 127.0.0.1:11434"
Write-Host ""
Write-Host "Keep this window open while using ShipVoice."
ssh -N shipvoice-gpu
