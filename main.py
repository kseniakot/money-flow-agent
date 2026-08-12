from app.config import config


def main() -> None:
    print("Config loaded:")
    print(f"  lm_base_url      = {config.lm_base_url}")
    print(f"  lm_model         = {config.lm_model}")
    print(f"  db_path          = {config.db_path}")
    print(f"  whisper_bin      = {config.whisper_bin}")
    print(f"  whisper_model    = {config.whisper_model}")
    print(f"  default_currency = {config.default_currency}")
    print(f"  tg_token set     = {bool(config.tg_token)}")


if __name__ == "__main__":
    main()
