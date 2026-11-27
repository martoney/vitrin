UUID := vitrin
FILES := $(UUID)/files/$(UUID)
EXT_DIR := $(HOME)/.local/share/cinnamon/extensions
VALIDATOR := https://raw.githubusercontent.com/linuxmint/cinnamon-spices-extensions/master/validate-spice

.PHONY: test unit integration validate install screenshot

test: unit validate integration

unit:
	node --test tests/unit/*.test.js

integration:
	tests/integration/run.py

validate:
	tmp=$$(mktemp -d) && cp -r $(UUID) $$tmp/$(UUID) && curl -fsSL -o $$tmp/validate-spice $(VALIDATOR) \
		&& (cd $$tmp && python3 validate-spice $(UUID)); status=$$?; rm -rf $$tmp; exit $$status

install:
	rm -rf $(EXT_DIR)/$(UUID)
	mkdir -p $(EXT_DIR)
	cp -r $(FILES) $(EXT_DIR)/$(UUID)
	gdbus call --session --dest org.Cinnamon --object-path /org/Cinnamon \
		--method org.Cinnamon.ReloadXlet $(UUID) EXTENSION >/dev/null

screenshot:
	tests/integration/run.py showcase showcase-neon
	cp tests/integration/out/showcase-crop.png $(UUID)/screenshot.png
	mkdir -p docs
	cp tests/integration/out/showcase-neon-crop.png docs/screenshot-neon.png
