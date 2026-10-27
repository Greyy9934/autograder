#include <stdio.h>

int main(void) {
    char input[100];

    if (fgets(input, sizeof(input), stdin) == NULL) {
        return 1;
    }

    printf("AutoGrader received: %s", input);
    return 0;
}
