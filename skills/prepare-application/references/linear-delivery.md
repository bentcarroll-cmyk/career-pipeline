# Verified Linear delivery

After local quality checks pass:

1. Verify the final local filenames and SHA-256 values.
2. Upload those exact resume and optional cover-letter PDFs to the resolved Linear ticket.
3. Read attachments back and verify count, filenames, sizes when available, and hashes or exact-byte identity when supported.
4. Add one concise comment stating which approved evidence was emphasized and listing actionable gaps. Do not copy private drafts or full review evidence into Linear.
5. Set `Packet ready` and read it back.
6. Record the delivery receipt in the application manifest.
7. Clear `Prepare application` only after attachment and label readback succeeds.

If any write or readback fails, keep `Prepare application`, persist the last verified stage, and report the exact retry point. Repeating a verified stage must reuse its receipt and must not create another attachment or comment.

`Packet ready` means materials were delivered; it never means the application was submitted.
