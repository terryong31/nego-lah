<script setup lang="ts">
useSeoMeta({
  title: 'Terms of Service',
  description: 'The terms and conditions for using the Nego-lah marketplace.'
})

const lastUpdated = 'June 2026'
</script>

<template>
  <div class="max-w-3xl mx-auto py-8">
    <h1 class="text-3xl font-bold text-highlighted">
      Terms of Service
    </h1>
    <p class="text-sm text-muted mt-2">
      Last updated: {{ lastUpdated }}
    </p>

    <div class="prose dark:prose-invert mt-8 space-y-6 text-toned">
      <section class="space-y-2">
        <h2 class="text-xl font-semibold text-highlighted">
          1. Acceptance of Terms
        </h2>
        <p>
          By accessing or using Nego-lah, you agree to be bound by these Terms of Service.
          If you do not agree, please do not use the service.
        </p>
      </section>

      <section class="space-y-2">
        <h2 class="text-xl font-semibold text-highlighted">
          2. Your Account
        </h2>
        <p>
          You are responsible for keeping your login credentials secure and for all activity
          under your account. You must provide accurate information and be at least the age of
          majority in your jurisdiction.
        </p>
      </section>

      <section class="space-y-2">
        <h2 class="text-xl font-semibold text-highlighted">
          3. Negotiations and Pricing
        </h2>
        <p>
          Prices on Nego-lah are negotiated with an AI seller. Any price agreed during a
          negotiation is an offer to transact; final sale is subject to availability and
          successful payment. We reserve the right to correct pricing errors.
        </p>
      </section>

      <section class="space-y-2">
        <h2 class="text-xl font-semibold text-highlighted">
          4. Orders and Payment
        </h2>
        <p>
          When you complete checkout you agree to pay the agreed amount. Payments are handled
          by our payment partners. Orders may be cancelled if payment fails or if the item is
          no longer available.
        </p>
      </section>

      <section class="space-y-2">
        <h2 class="text-xl font-semibold text-highlighted">
          5. Acceptable Use
        </h2>
        <ul class="list-disc pl-6 space-y-1">
          <li>Do not use the service for any unlawful or fraudulent purpose.</li>
          <li>Do not attempt to disrupt, reverse engineer, or abuse the AI or platform.</li>
          <li>Do not misrepresent items, prices, or your identity.</li>
        </ul>
      </section>

      <section class="space-y-2">
        <h2 class="text-xl font-semibold text-highlighted">
          6. Disclaimer
        </h2>
        <p>
          The service is provided "as is" without warranties of any kind. We do not guarantee
          uninterrupted availability or that AI-generated responses are error-free.
        </p>
      </section>

      <section class="space-y-2">
        <h2 class="text-xl font-semibold text-highlighted">
          7. Limitation of Liability
        </h2>
        <p>
          To the maximum extent permitted by law, Nego-lah is not liable for any indirect,
          incidental, or consequential damages arising from your use of the service.
        </p>
      </section>

      <section class="space-y-2">
        <h2 class="text-xl font-semibold text-highlighted">
          8. Changes to These Terms
        </h2>
        <p>
          We may update these terms from time to time. Continued use of the service after
          changes take effect constitutes acceptance of the revised terms.
        </p>
      </section>

      <section class="space-y-2">
        <h2 class="text-xl font-semibold text-highlighted">
          9. Contact
        </h2>
        <p>
          Questions about these terms? Reach out to
          <ULink
            to="mailto:hello@negolah.my"
            class="text-primary"
          >hello@negolah.my</ULink>.
        </p>
      </section>
    </div>
  </div>
</template>
