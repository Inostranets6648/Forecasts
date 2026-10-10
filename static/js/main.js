document.addEventListener("DOMContentLoaded", () => {
    const flashMessages = document.querySelectorAll(".flash-message");
    if (flashMessages.length > 0) {
        setTimeout(() => {
            flashMessages.forEach(msg => {
                msg.style.transition = "opacity 0.4s ease, transform 0.4s ease";
                msg.style.opacity = "0";
                msg.style.transform = "translateY(-8px)";
                setTimeout(() => msg.remove(), 400);
            });
        }, 4000);
    }

    const dateInput = document.getElementById("target_date");
    const chips = document.querySelectorAll(".date-chip");

    if (dateInput && chips.length > 0) {
        chips.forEach(chip => {
            chip.addEventListener("click", () => {
                const now = new Date();
                const addDays = parseInt(chip.dataset.days || "0", 10);
                const addHours = parseInt(chip.dataset.hours || "0", 10);

                now.setDate(now.getDate() + addDays);

                if (addHours) {
                    now.setHours(now.getHours() + addHours);
                } else {
                    now.setHours(20, 0, 0, 0);
                }

                const pad = num => String(num).padStart(2, "0");
                const yyyy = now.getFullYear();
                const mm = pad(now.getMonth() + 1);
                const dd = pad(now.getDate());
                const hh = pad(now.getHours());
                const min = pad(now.getMinutes());

                dateInput.value = `${yyyy}-${mm}-${dd}T${hh}:${min}`;
            });
        });
    }

    const typeTask = document.getElementById("type-task");
    const typeForecast = document.getElementById("type-forecast");
    const forecastCondition = document.getElementById("forecast-condition-group");
    const dateLabel = document.getElementById("date-label");

    if (typeTask && typeForecast && forecastCondition) {
        function toggleTypeFields() {
            if (typeForecast.checked) {
                forecastCondition.style.display = "block";
                if (dateLabel) dateLabel.textContent = "Дата наступления прогноза";
            } else {
                forecastCondition.style.display = "none";
                if (dateLabel) dateLabel.textContent = "Срок исполнения (дедлайн)";
            }
        }

        typeTask.addEventListener("change", toggleTypeFields);
        typeForecast.addEventListener("change", toggleTypeFields);
        toggleTypeFields();
    }
});
