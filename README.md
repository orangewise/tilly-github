# tilly-github

Tilly plugin for publishing with Github, inspired by [Simon Willison: TIL](https://til.simonwillison.net).

## Customize the default templates

Your can overwrite the default templates by first making a copy of the default templates:

```
tilly github copy-templates
```

Change the templates to your liking, then generate your static site:

```
tilly github gen-static --template-dir templates
```

Customized templates can also be served locally:

```
tilly github serve --template-dir templates
```