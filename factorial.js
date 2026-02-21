function factorial(n) {
    // Handle edge cases
    if (n < 0) {
        return "Factorial is not defined for negative numbers";
    }
    if (n === 0 || n === 1) {
        return 1;
    }
    
    // Calculate factorial recursively
    return n * factorial(n - 1);
}

// Test the function
console.log(factorial(5));   // Output: 120
console.log(factorial(0));   // Output: 1
console.log(factorial(10));  // Output: 3628800