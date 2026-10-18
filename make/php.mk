# PHP: Composer, PHPUnit or Pest, PHPStan, Laravel Pint or PHP-CS-Fixer.
PHP_TEST ?= $(if $(wildcard vendor/bin/pest),vendor/bin/pest,vendor/bin/phpunit)
PHP_STAN ?= vendor/bin/phpstan
PHP_STAN_ARGS ?= analyse --no-progress
PHP_STYLE ?= $(if $(wildcard vendor/bin/pint),vendor/bin/pint,vendor/bin/php-cs-fixer)
PHP_STYLE_CHECK_ARGS ?= $(if $(findstring pint,$(PHP_STYLE)),--test,fix --dry-run --diff)
PHP_STYLE_FIX_ARGS ?= $(if $(findstring pint,$(PHP_STYLE)),,fix)

.PHONY: install-php typecheck-php lint-php test-php fmt-php

install-php:
	composer install --no-interaction

typecheck-php:
	$(call need,$(PHP_STAN),composer require --dev phpstan/phpstan)
	$(PHP_STAN) $(PHP_STAN_ARGS)

lint-php:
	$(call need,$(PHP_STYLE),composer require --dev laravel/pint  (or friendsofphp/php-cs-fixer))
	$(PHP_STYLE) $(PHP_STYLE_CHECK_ARGS)

test-php:
	$(call need,$(PHP_TEST),composer require --dev phpunit/phpunit  (or pestphp/pest))
	$(PHP_TEST)

fmt-php:
	$(call need,$(PHP_STYLE),composer require --dev laravel/pint)
	$(PHP_STYLE) $(PHP_STYLE_FIX_ARGS)
