APP_NAME := mapper
ENTRY := src/$(APP_NAME)/runtime/runtime.py
GRAMMER := src/$(APP_NAME)/syntax/mapping.lark
.RECIPEPREFIX := >

.PHONY: install build run clean

install:
>uv sync --dev

build:
>uv run pyinstaller --onefile --name $(APP_NAME) --hidden-import mapper.syntax.builder --collect-submodules mapper --collect-data lark --copy-metadata lark --add-data "$(GRAMMER);mapper/syntax" $(ENTRY)

run: build
>cd data && ..\dist\$(APP_NAME).exe example.mapping

clean:
>if exist build rmdir /s /q build
>if exist dist  rmdir /s /q dist
>del /q $(APP_NAME).spec 2>nul