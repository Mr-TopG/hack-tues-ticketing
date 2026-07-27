document.addEventListener("DOMContentLoaded", () => {
    if (typeof window.flatpickr !== "function") {
        return;
    }

    const pickerInputs = document.querySelectorAll(
        ".js-datetime-picker"
    );

    pickerInputs.forEach((input) => {
        window.flatpickr(input, {
            enableTime: true,
            enableSeconds: false,
            time_24hr: true,
            minuteIncrement: 5,

            dateFormat: "Y-m-d H:i",
            altInput: true,
            altFormat: "D, d M Y — H:i",

            allowInput: true,
            disableMobile: true,
            monthSelectorType: "dropdown",

            defaultHour: 12,
            defaultMinute: 0,

            position: "auto center",

            locale: {
                firstDayOfWeek: 1,
            },

            prevArrow: "‹",
            nextArrow: "›",
        });
    });

    const scopes = document.querySelectorAll(
        "[data-picker-scope]"
    );

    scopes.forEach((scope) => {
        const startInputs = scope.querySelectorAll(
            '[data-picker-role="start"]'
        );

        startInputs.forEach((startInput) => {
            const group = startInput.dataset.pickerGroup;

            const endInput = scope.querySelector(
                `[data-picker-group="${group}"]`
                + '[data-picker-role="end"]'
            );

            if (
                !endInput
                || !startInput._flatpickr
                || !endInput._flatpickr
            ) {
                return;
            }

            const startPicker = startInput._flatpickr;
            const endPicker = endInput._flatpickr;

            const applyMinimum = (dates) => {
                const selectedStart = dates[0] || null;

                endPicker.set(
                    "minDate",
                    selectedStart,
                );
            };

            startPicker.config.onChange.push(applyMinimum);

            if (startPicker.selectedDates.length > 0) {
                applyMinimum(startPicker.selectedDates);
            }
        });
    });
});
