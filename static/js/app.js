document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll('input[type="date"]').forEach(input => {
    if (!input.value && input.name === "start_date") input.min = new Date().toISOString().slice(0,10);
  });
});
