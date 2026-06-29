<script setup lang="ts">
useSeoMeta({
  title: 'Privacy Policy',
  description: 'How Nego-lah collects, uses, and protects your personal information.'
})

const lastUpdated = 'June 2026'
</script>

<template>
  <div class="max-w-3xl mx-auto py-8">
    <h1 class="text-3xl font-bold text-highlighted">
      Privacy Policy
    </h1>
    <p class="text-sm text-muted mt-2">
      Last updated: {{ lastUpdated }}
    </p>

    <div class="prose dark:prose-invert mt-8 space-y-6 text-toned">
      <section class="space-y-2">
        <h2 class="text-xl font-semibold text-highlighted">
          1. Introduction
        </h2>
        <p>
          Nego-lah ("we", "us", "our") operates a second-hand marketplace where buyers
          negotiate prices with an AI seller. This policy explains what data we collect,
          why we collect it, and how we keep it safe.
        </p>
      </section>

      <section class="space-y-2">
        <h2 class="text-xl font-semibold text-highlighted">
          2. Information We Collect
        </h2>
        <ul class="list-disc pl-6 space-y-1">
          <li><strong>Account data:</strong> your email address and authentication details.</li>
          <li><strong>Usage data:</strong> items you view, chats you start, and negotiation history.</li>
          <li><strong>Transaction data:</strong> orders placed and payment confirmations (we do not store card details).</li>
          <li><strong>Technical data:</strong> device, browser, and basic analytics needed to run the service.</li>
        </ul>
      </section>

      <section class="space-y-2">
        <h2 class="text-xl font-semibold text-highlighted">
          3. How We Use Your Information
        </h2>
        <ul class="list-disc pl-6 space-y-1">
          <li>To create and manage your account.</li>
          <li>To power AI-assisted negotiations and process your orders.</li>
          <li>To improve the marketplace and surface relevant listings.</li>
          <li>To communicate important updates and respond to support requests.</li>
        </ul>
      </section>

      <section class="space-y-2">
        <h2 class="text-xl font-semibold text-highlighted">
          4. Payments
        </h2>
        <p>
          Payments are processed by third-party payment providers. Your card information is
          handled directly by those providers and is never stored on our servers.
        </p>
      </section>

      <section class="space-y-2">
        <h2 class="text-xl font-semibold text-highlighted">
          5. Data Sharing
        </h2>
        <p>
          We do not sell your personal data. We share information only with service providers
          that help us operate Nego-lah (such as hosting, authentication, and payment partners),
          or when required by law.
        </p>
      </section>

      <section class="space-y-2">
        <h2 class="text-xl font-semibold text-highlighted">
          6. Your Rights
        </h2>
        <p>
          You may access, correct, or delete your account data at any time from your
          <ULink
            to="/profile"
            class="text-primary"
          >profile settings</ULink>, or by contacting us.
        </p>
      </section>

      <section class="space-y-2">
        <h2 class="text-xl font-semibold text-highlighted">
          7. Contact
        </h2>
        <p>
          Questions about this policy? Reach out to
          <ULink
            to="mailto:hello@negolah.my"
            class="text-primary"
          >hello@negolah.my</ULink>.
        </p>
      </section>
    </div>
  </div>
</template>
