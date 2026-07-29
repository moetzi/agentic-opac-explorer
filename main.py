import os
import uuid
import logging
from dotenv import load_dotenv, find_dotenv

# Import Arsitektur Workflow Baru (While-Loop Based)
from agent.core.workflow import run_workflow
from agent.services.database import get_driver
from agent.services.llm_services import get_llm

load_dotenv(find_dotenv())

# Konfigurasi logging agar rapi di terminal
logging.basicConfig(
    level=logging.INFO, 
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S"
)

# --- 1. Inisialisasi Environment ---
# Pastikan LLM default sudah siap dari awal
provider = os.getenv("ACTIVE_LLM_PROVIDER", "ollama").lower()
llm = get_llm(provider)

session_id = str(uuid.uuid4())[:8] 

print("="*60)
print(f"=== SYSTEM PUSTAKAWAN JAKARTA (Session: {session_id}) ===")
print(f"Mesin Inference Aktif: {provider.upper()}")
print("Ketik 'exit' atau 'quit' untuk keluar.\n")
print("="*60)

try:
    while True:
        user_input = input("\nTanya Pustakawan: ")

        if user_input.lower() in ["exit", "quit"]:
            break
            
        if not user_input.strip():
            continue

        print("\n[*] Pustakawan sedang berpikir dan mencari di database...\n")
        
        # Eksekusi full workflow (While-Loop manual yang ada di workflow.py)
        result = run_workflow(query=user_input)
        
        # --- MENAMPILKAN HASIL ---
        print("\n" + "─"*60)
        print("💬 JAWABAN PUSTAKAWAN:")
        print("─"*60)
        print(result.final_answer)
        print("─"*60)

        # Jika kamu butuh melihat log eksekusi, kamu bisa mencetaknya
        # (Bisa dikomentari jika kamu hanya ingin melihat hasil akhir)
        print("\n📋 TOOL CHAIN LOG:")
        for step in result.tool_chain_log:
            print(f"  → {step}")
            
        if result.is_hallucinating or result.retry_count > 0:
            print(f"\n⚠️ Sempat Terjadi Halusinasi: {result.is_hallucinating}")
            print(f"🔄 Total Retry/Koreksi    : {result.retry_count} kali")

except KeyboardInterrupt:
    print("\nShutting down...")
finally:
    # Mengambil objek driver lalu menutupnya secara aman
    driver = get_driver()
    if driver is not None:
        driver.close()
    print("Database connection closed. Bye!")